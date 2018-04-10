from __future__ import division, absolute_import, print_function

import time
import multiprocessing
import math
import glob
import os
import shutil
import argparse

import numpy as np
from baselines.common import set_global_seeds

import environments.kuka_button_gym_env as kuka_env
import environments.kuka_2button_gym_env as kuka_env_2
import environments.kuka_rand_button_gym_env as kuka_env_rand
from srl_priors.utils import printRed

kuka_env.RECORD_DATA = True
# Reduce max distance to have more negative rewards for srl
kuka_env.MAX_DISTANCE = 0.65

parser = argparse.ArgumentParser(description='Create frames from a test env')
parser.add_argument('--num-cpu', type=int, default=4,
                    help='number of cpu to run on (default: 4)')
parser.add_argument('--num-episode', type=int, default=50, 
                    help='number of episode to run (default: 50)')
parser.add_argument('--save-folder', type=str, default='srl_priors/data/',
                    help='Folder where the environments will save the output')
parser.add_argument('--save-name', type=str, default='kuka_button',
                    help='Folder name for the output')
parser.add_argument('--env', type=str, default='KukaButtonGymEnv',
                    choices=["KukaButtonGymEnv", "Kuka2ButtonGymEnv", "KukaRandButtonGymEnv"],
                    help='The environment wanted')
parser.add_argument('--no-display', action='store_true', default=False)
parser.add_argument('-c', '--continuous-actions', action='store_true', default=False)


args = parser.parse_args()

SEEDS = range(args.num_cpu)

# to avoid overriding by accident
assert not os.path.exists(args.save_folder+args.save_name), \
    "Error: save directory '{}' already exists".format(args.save_folder+args.save_name)

def env_thread(thread_num):
    set_global_seeds(SEEDS[thread_num])
    if args.env == "KukaButtonGymEnv":
        env = kuka_env.KukaButtonGymEnv(renders=(thread_num==0 and not args.no_display), is_discrete=(not args.continuous_actions), name=args.save_name+"_part-"+str(thread_num))
    elif args.env == "Kuka2ButtonGymEnv":
        env = kuka_env_2.Kuka2ButtonGymEnv(renders=(thread_num==0 and not args.no_display), is_discrete=(not args.continuous_actions), name=args.save_name+"_part-"+str(thread_num)) 
    elif args.env == "KukaRandButtonGymEnv":
        env = kuka_env_rand.KukaRandButtonGymEnv(renders=(thread_num==0 and not args.no_display), is_discrete=(not args.continuous_actions), name=args.save_name+"_part-"+str(thread_num))

    i = 0
    start_time = time.time()
    # divide evenly, then do an extra one for only some of them in order to get the right count
    for i_episode in range(args.num_episode//args.num_cpu + 1*(args.num_episode%args.num_cpu>thread_num)):
        observation = env.reset()
        done = False
        t = 0
        while not done:
            env.render()
            action = env.action_space.sample()
            observation, reward, done, info = env.step(action)
            i += 1
            t += 1
            if done:
                print("Episode finished after {} timesteps".format(t+1))

        if thread_num == 0:
            print("{:.2f} FPS".format(i*args.num_cpu / (time.time() - start_time)))


# try and divide into multiple processes, with an environment each
try:
    jobs = []
    for i in range(args.num_cpu):
        process = multiprocessing.Process(target=env_thread, args=(i,))
        jobs.append(process)

    for j in jobs:
        j.start()

    try:
        for j in jobs:
            j.join()
    except:
        printRed("Error: unable to join thread")
        os.exit(-1)

except:
    printRed("Error: unable to start thread")
    os.exit(-1)

# get all the parts 
file_parts = glob.glob(args.save_folder+args.save_name+"_part-[0-9]*")

# create the output
os.mkdir(args.save_folder+args.save_name)

# move the config files from any as they are identical
os.rename(file_parts[0]+"/dataset_config.json", 
    args.save_folder+args.save_name+"/dataset_config.json")
os.rename(file_parts[0]+"/env_globals.json",
    args.save_folder+args.save_name+"/env_globals.json")

ground_truth = None
preprocessed_data = None

def convertImagePath(path, record_id_start):
    """
    Used to convert an image path, from one location, to an other
    :param path: (str)
    :param record_id_start: (int) where does the current part start counting its records
    :return:
    """
    image_name = path.split("/")[-1]
    # get record id for output, by adding the current offset with the record_id
    # of the folder
    id = record_id_start + int(path.split("/")[-2].split("_")[-1])
    return args.save_name+"/record_{:03d}".format(id) + "/" + image_name

# used to convert the part record_id to the fused record_id
record_id = 0
for part in file_parts:
    # sort the record names alphabetically, then numerically
    records = sorted(glob.glob(part+"/record_[0-9]*"), 
        key=lambda a: int(a.split("_")[-1]))

    record_id_start = record_id
    for record in records:
        os.renames(record, args.save_folder+args.save_name+"/record_{:03d}".format(record_id))
        record_id += 1

    # fuse the npz files together, in the right order
    if ground_truth is None:
        # init
        ground_truth = {}
        preprocessed_data = {}
        ground_truth_load = np.load(part+"/ground_truth.npz")
        preprocessed_data_load = np.load(part+"/preprocessed_data.npz")

        for arr in ground_truth_load.files:
            if arr == "images_path":
                ground_truth[arr] = np.array([convertImagePath(path, record_id_start)\
                    for path in ground_truth_load[arr]])
            else:
                ground_truth[arr] = ground_truth_load[arr]
        for arr in preprocessed_data_load.files:
            preprocessed_data[arr] = preprocessed_data_load[arr]

    else:
        ground_truth_load = np.load(part+"/ground_truth.npz")
        preprocessed_data_load = np.load(part+"/preprocessed_data.npz")

        for arr in ground_truth_load.files:
            if arr == "images_path":
                sanitised_paths = np.array([convertImagePath(path, record_id_start)\
                    for path in ground_truth_load[arr]])
                ground_truth[arr] = np.concatenate((ground_truth[arr],sanitised_paths))
            else:
                ground_truth[arr] = np.concatenate((ground_truth[arr],ground_truth_load[arr]))
        for arr in preprocessed_data_load.files:
            preprocessed_data[arr] = np.concatenate((preprocessed_data[arr],preprocessed_data_load[arr]))

    # remove the current part folder
    shutil.rmtree(part)

# save the fused outputs
np.savez(args.save_folder+args.save_name+"/ground_truth.npz", **ground_truth)
np.savez(args.save_folder+args.save_name+"/preprocessed_data.npz", **preprocessed_data)