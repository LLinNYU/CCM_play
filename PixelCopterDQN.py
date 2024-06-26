#!/usr/bin/env python
# coding: utf-8

# ## **SET UP PYGAME ENVIRONMENT**

# In[ ]:


# ONLY NEED TO RUN ONCE
# import os
# get_ipython().system('git clone https://github.com/ntasfi/PyGame-Learning-Environment/')
# os.chdir("PyGame-Learning-Environment")
# print(f"Current directory {os.getcwd()}")
# get_ipython().system('pip install -e .')
# get_ipython().system('pip install pygame')
# get_ipython().system('pip install -q tensorflow')
# get_ipython().system('pip install -q keras')


# # Imports

import datetime
import os
import platform
import random
import sys
import time
from collections import deque
import h5py


import keras
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn as sk
import tensorflow as tf
from tqdm import tqdm
from keras import Sequential
from keras.callbacks import TensorBoard
from keras.layers import Dense, Dropout, BatchNormalization
from keras.optimizers import Adam
from keras import initializers
from ple import PLE
from ple.games.pixelcopter import Pixelcopter


print(f"Tensor Flow Version: {tf.__version__}")
print(f"Keras Version: {keras.__version__}")
print()
print(f"Python {sys.version} {platform.system()}")
print(f"Pandas {pd.__version__}")
print(f"Scikit-Learn {sk.__version__}")
gpu = len(tf.config.list_physical_devices('GPU')) > 0
print("GPU is", "available" if gpu else "NOT AVAILABLE")

# Sets the initial window position of the game
x = 1200  
y = 200
os.environ['SDL_VIDEO_WINDOW_POS'] = "%d,%d" % (x, y)


# Own Tensorboard class
class ModifiedTensorBoard(TensorBoard):

    # Overriding init to set initial step and writer (we want one log file for all .fit() calls)
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.step = 1
        self.writer = tf.summary.create_file_writer(self.log_dir)
        self.log_write_dir = self.log_dir
        self._train_dir = os.path.join(self.log_dir + 'train')
        self._val_dir = os.path.join(self.log_dir, 'validation')
        self._should_write_train_graph = False

    # Overriding this method to stop creating default log writer
    def set_model(self, model):
        self.model = model
        self._train_step = self.model._train_counter
        self._val_step = self.model._test_counter

    # Overrides, saves logs with our step number
    # (otherwise every .fit() will start writing from 0th step)
    def on_epoch_end(self, epoch, logs=None):
        self.update_stats(**logs)

    # Overrides
    # We train for one batch only, no need to save anything at epoch end
    def on_batch_end(self, batch, logs=None):
        pass

    # Overrides, so won't close writer
    def on_train_end(self, logs=None):
        pass

    # Custom method for saving own metrics
    # Creates writer, writes custom metrics and closes writer
    def update_stats(self, **stats):
        with self.writer.as_default():
            for key, value in stats.items():
                tf.summary.scalar(key, value, step=self.step)
                self.writer.flush()


class DQNAgent:
    # hyper-parameters
    INPUT_SIZE = 7
    OUTPUT_SIZE = 2
    EPSILON = 1
    MIN_EPSILON = 0.05
    GAMMA = 0.99
    MIN_MEMORY_SIZE = 1000
    UPDATE_TARGET_LIMIT = 3

    # based on documentation, state has 7 features
    # output is 2 dimensions, 0 = do nothing, 1 = jump

    def __init__(self, mode="train", nodes=32, memory_size=5000, final_act="linear", minibatch=32,
                 lr=1e-2, num_episodes=1000):
        # depending on what mode the agent is in, will determine how the agent chooses actions
        # if agent is training, EPSILON = 1 and will decay over time with epsilon probability of exploring
        # if agent is playing (using trained model), EPSILON = 0 and only choose actions based on Q network
        self.DECAY_RATE = 5 / num_episodes
        self.HIDDEN_NODES = nodes
        self.MEMORY_SIZE = memory_size
        self.FINAL_ACTIVATION = final_act
        self.MINIBATCH_SIZE = minibatch
        self.LEARNING_RATE = lr
        self.EPSILON = 1 if mode == "train" else 0
        self.MODEL_NAME = f"model - ({lr} {minibatch} {memory_size} {nodes} {final_act} {num_episodes})"
        self.MODEL_FILE = "dqn/best/model - (0.01 64 10000 49 linear 10000___111.11max___23.35avg___-3.82min.h5"
        # main model  # gets trained every step
        self.model = self.create_model()
        print(self.model.summary())
        print("Finished building baseline model..")
        self.action_map = {
            0: None,
            1: 119
        }

        log_dir_path = f"logs/{self.MODEL_NAME}-{int(time.time())}"
        if not os.path.exists(log_dir_path):
            os.makedirs(log_dir_path)
        # Target model this is what we predict against every step
        self.target_model = self.create_model()
        print("Finished building target model..")
        self.target_model.set_weights(self.model.get_weights())
        self.replay_memory = deque(maxlen=self.MEMORY_SIZE)
        self.tensorboard = ModifiedTensorBoard(log_dir=log_dir_path) if mode == "train" else None
        self.target_update_counter = 0
        self.rewards = []

    def create_model(self):
        model = Sequential()

        model.add(Dense(32, input_shape=(self.INPUT_SIZE,), activation="relu"))

        model.add(Dense(64, activation="relu"))
        model.add(Dropout(0.2))

        model.add(Dense(64, activation="relu"))
        model.add(Dropout(0.2))

        model.add(Dense(self.OUTPUT_SIZE, activation='linear'))  # ACTION_SPACE_SIZE = how many choices (9)
        model.compile(loss="mse", optimizer=Adam(lr=self.LEARNING_RATE), metrics=['accuracy'])
        return model

    def update_replay_memory(self, state, action, reward, new_state, done):
        self.replay_memory.append((state, action, reward, new_state, done))
        if len(self.replay_memory) > self.MEMORY_SIZE:
            self.replay_memory.popleft()

    def select_action(self, state):
        # chose random action with probability epsilon
        if np.random.uniform() < self.EPSILON:
            # to speed up training give higher probability to action 0 (no jump)
            action_index = np.random.choice([0, 1], size=1, p=[0.8, 0.2])[0]
            # action_index = np.random.randint(self.OUTPUT_SIZE)
        else:
            # otherwise chose epsilon-greedy action from neural net
            action_index = self.get_predicted_action([state])
        actual_action = self.action_map[action_index]
        return action_index, actual_action

    def get_predicted_action(self, sequence):
        prediction = self.model.predict(np.array(sequence))[0]
        # print("Prediction", prediction)
        return np.argmax(prediction)

    def construct_memories(self):
        # Get a minibatch of random samples from memory replay table
        replay = random.sample(self.replay_memory, self.MINIBATCH_SIZE)
        # Get current states from minibatch, then query NN model for Q values
        states = np.array([step[0] for step in replay])
        Q = self.model.predict(states)
        # Get future states from minibatch, then query NN model for Q values
        new_states = np.array([step[3] for step in replay])
        Q_next = self.model.predict(new_states)

        X = []
        Y = []

        for index, (state, action, reward, state_, done) in enumerate(replay):
            # If not a terminal state, get new q from future states, otherwise set it to 0
            # almost like with Q Learning, but we use just part of equation here
            if not done:
                max_Q = np.amax(Q_next[index])
                new_Q = reward + self.GAMMA * max_Q
            else:
                new_Q = reward

            # Update the Q value for given state
            target = Q[index]
            target[action] = new_Q

            # Append new values to training data
            X.append(state)
            Y.append(target)
        return np.array(X), np.array(Y)

    def train(self, is_terminal, step):
        if not os.path.isdir('dqn'):
            os.makedirs('dqn')

        # Start training only if certain number of samples is already saved
        if len(self.replay_memory) < self.MIN_MEMORY_SIZE:
            return

        # constructs training data for training of the neural network
        X, y = self.construct_memories()

        # Update target network counter after every episode
        if is_terminal:
            self.model.fit(
                X,
                y,
                batch_size=self.MINIBATCH_SIZE,
                verbose=1,
                shuffle=False,
                callbacks=[self.tensorboard]
            )
            self.target_update_counter += 1

        # If counter reaches a set value, update the target network with weights of main network
        if self.target_update_counter > self.UPDATE_TARGET_LIMIT:
            self.target_model.set_weights(self.model.get_weights())
            self.target_update_counter = 0


def init():
    # HYPER PARAMETERS TO SEARCH
    hidden_layer_nodes = np.arange(32, 481, 32)  # 32, 64, 96, 128 ....
    num_episodes = [2500, 5000, 10_000, 20_000]
    replay_memory_size = [1000, 2000, 3000, 5000]
    final_layer_activation = ["linear"]
    minibatch_sizes = [16, 32, 64]
    learning_rates = [1e-2, 1e-3, 1e-4]

    for num_episode in num_episodes:
        for nodes in hidden_layer_nodes:
            for mem_size in replay_memory_size:
                for minibatch in minibatch_sizes:
                    for final_act in final_layer_activation:
                        for lr in learning_rates:
                            learn(nodes, num_episode, mem_size, final_act, minibatch, lr)


# Train Q network for a DQN agent
def learn(nodes=49, num_episodes=5000, memory_size=10_000, final_act="linear", minibatch=32, lr=1e-2):
    print(f"LEARNING PARAMS: nodes={nodes} num_episodes={num_episodes} memory_size={memory_size} " \
          f"final_act={final_act} batch={minibatch} lr={lr}")
    game = Pixelcopter(width=250, height=250)
    env = PLE(game, fps=30, display_screen=True, force_fps=True)
    env.init()
    episode_rewards = []
    agent = DQNAgent("train", nodes, memory_size, final_act, minibatch, lr, num_episodes)
    interval = 100
    offset = 1
    # Save model, but only when min reward is greater or equal a set value
    if not os.path.isdir(os.path.join(os.getcwd(), f"dqn/{agent.MODEL_NAME}")):
        os.mkdir(os.path.join(os.getcwd(), f"dqn/{agent.MODEL_NAME}"))
    for episode in range(1, num_episodes + 1):
        print("Episode : ", episode)
        agent.tensorboard.step = episode
        done = False
        step = 1
        total_reward = 0.0
        # initial state
        state = np.array(list(env.getGameState().values()))
        # print("State:", state)
        while not done:
            if env.game_over():
                print("GAME OVER!")
                print("Total reward", total_reward)
                done = True
            action_index, action = agent.select_action(state)
            action_string = 'jump!' if action_index == 1 else 'chill'
            # print("Action:", action, action_string)
            reward = env.act(action)
            # print("Reward:", reward)
            new_state = np.array(list(env.getGameState().values()))
            # update total reward
            total_reward += reward
            # update replay memory
            agent.update_replay_memory(state, action_index, reward, new_state, done)
            # update q_network
            agent.train(done, step)
            # update current state with new state
            state = new_state
            # increment time step
            step += 1
        # perform update only if a new max. reward was obtained after an episode (allow offset value of 5 for current max reward)
        if len(episode_rewards) > 0 and total_reward > (np.max(episode_rewards) - offset):
            can_update = True
        else:
            can_update = False
        # Append episode rewards to list of all episode rewards
        episode_rewards.append(total_reward)
        if can_update or episode == 1:
            average_reward = np.mean(episode_rewards[-interval:])
            min_reward = np.min(episode_rewards[-interval:])
            max_reward = np.max(episode_rewards[-interval:])
            agent.tensorboard.update_stats(
                reward_avg=average_reward,
                reward_min=min_reward,
                reward_max=max_reward,
                epsilon=agent.EPSILON
            )
            # Save model, but only when min reward is greater or equal a set value
            agent.model.save(
                f'dqn/{agent.MODEL_NAME}/{agent.MODEL_NAME}__{max_reward:_>7.2f}max_{average_reward:_>7.2f} avg_{min_reward:_>7.2f}min.h5')
        # Decay epsilon
        if agent.EPSILON > agent.MIN_EPSILON:
            agent.EPSILON -= agent.DECAY_RATE
            print("EPSILON", agent.EPSILON)
            # ensure epsilon does not subside below minimum value
            agent.EPSILON = max(agent.MIN_EPSILON, agent.EPSILON)
        env.reset_game()
    plot_graph(episode_rewards, num_episodes, nodes, memory_size, final_act, minibatch, lr)


def plot_graph(episode_rewards, num_episodes, nodes, memory_size, final_act, minibatch, lr):
    fig, ax = plt.subplots(nrows=1, figsize=(12, 15))
    episodes = np.arange(1, len(episode_rewards) + 1)
    ax.plot(episodes, episode_rewards)
    ax.legend(loc="best")
    ax.set_title("Learning curve for DQN agent")
    ax.set_xlabel("Number of episodes")
    ax.set_ylabel("Reward")
    plt.show()
    plt.savefig(
        f"graphs/DQN learning curve - num_episodes={num_episodes} hidden_nodes={nodes} mem_size={memory_size} final_act={final_act} minibatch={minibatch} lr={lr}.png")
    return True


# run the game using best DQN model
def play():
    game = Pixelcopter(width=250, height=250)
    env = PLE(game, fps=30, display_screen=True, force_fps=True)
    env.init()
    agent = DQNAgent("play")
    step = 0
    total_reward = 0
    state = np.array(list(env.getGameState().values()))
    while True:
        if env.game_over():
            print("===========================")
            print("TOTAL REWARD: ", total_reward)
            step = 0
            total_reward = 0
            env.reset_game()

        action_index, action = agent.select_action(state)
        # obtime.sleep(0.05)
        # action_string = 'jump!' if action_index == 1 else 'chill'
        reward = env.act(action)
        new_state = np.array(list(env.getGameState().values()))

        # PRINT CURRENT STATS
        # print("Current State:", state)
        # print("Action:", action, action_string)
        # print("Reward:", reward)
        # print("New State:", new_state)

        state = new_state
        step += 1
        total_reward += reward


if __name__ == "__main__":
    play()
    # learn(nodes=49, num_episodes=5000, lr=1e-2)
