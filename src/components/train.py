import os

from kfp.v2.dsl import Dataset, Input, Metrics, Model, Output, component


@component(
    base_image='python:3.10-slim',
    packages_to_install=[
        'pandas',
        'scikit-learn',
        'tensorflow',
        'keras',
    ],
    output_component_file=os.path.join('configs', 'train.yaml'),
)
def train(
    feature: str,
    lookback: int,
    lstm_units: int,
    learning_rate: float,
    epochs: int,
    batch_size: int,
    patience: int,
    train_data: Input[Dataset],
    scaler_model: Output[Model],
    keras_model: Output[Model],
    metrics: Output[Metrics],
) -> None:
    """Instantiates, trains the RNN model on the train dataset. Saves the trained scaler and the keras model to the metadata store, saves the evaluation metrics file as well.

    Args:
        feature (str): Feature string to train on
        lookback (int): Length of the lookback window
        lstm_units (int): Number of the LSTM units in the RNN
        learning_rate (float): Initial learning rate
        epochs (int): Number of epochs to train
        batch_size (int): Batch size
        patience (int): Number of patient epochs before the callbacks activate
        train_data (Input[Dataset]): Train dataset
        scaler_model (Output[Model]): Scaler model
        keras_model (Output[Model]): Keras model
        metrics (Output[Metrics]): Metrics
    """
    import joblib
    import json

    import keras
    import numpy as np
    import pandas as pd
    from sklearn.preprocessing import MinMaxScaler

    train_df = pd.read_csv(train_data.path + '.csv', index_col=False)
    train_data = train_df[feature].values.reshape(-1, 1)
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_train = scaler.fit_transform(train_data)
    scaler_model.metadata['feature'] = feature
    joblib.dump(scaler, scaler_model.path + f'_{feature}.joblib')
    x_train, y_train = [], []
    for i in range(lookback, len(scaled_train)):
        x_train.append(scaled_train[i - lookback:i])
        y_train.append(scaled_train[i])
    x_train = np.stack(x_train)
    y_train = np.stack(y_train)
    forecaster = keras.models.Sequential()
    forecaster.add(
        keras.layers.LSTM(lstm_units,
                          input_shape=(x_train.shape[1], x_train.shape[2]),
                          return_sequences=False))
    forecaster.add(keras.layers.Dense(1))
    forecaster.compile(
        loss=keras.losses.mean_squared_error,
        metrics=keras.metrics.RootMeanSquaredError(),
        optimizer=keras.optimizers.RMSprop(learning_rate=learning_rate))
    history = forecaster.fit(
        x_train,
        y_train,
        shuffle=False,
        epochs=epochs,
        batch_size=batch_size,
        validation_split=0.2,
        verbose=1,
        callbacks=[
            keras.callbacks.EarlyStopping(patience=patience,
                                          monitor='val_loss',
                                          mode='min',
                                          verbose=1,
                                          restore_best_weights=True),
            keras.callbacks.ReduceLROnPlateau(monitor='val_loss',
                                              factor=0.75,
                                              patience=patience // 2,
                                              verbose=1,
                                              mode='min'),
        ])
    with open(metrics.path + f'_{feature}.json', 'w') as mterics_file:
        for k, v in history.history.items():
            history.history[k] = [float(vi) for vi in v]
            metrics.log_metric(k, history.history[k])
        mterics_file.write(json.dumps(history.history))
    metrics.metadata['feature'] = feature
    keras_model.metadata['feature'] = feature
    forecaster.save(keras_model.path + f'_{feature}.h5')