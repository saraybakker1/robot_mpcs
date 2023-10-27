import sys
import os
import numpy as np
import gymnasium as gym
from urdfenvs.robots.generic_urdf.generic_diff_drive_robot import GenericDiffDriveRobot
from urdfenvs.sensors.occupancy_sensor import OccupancySensor
from mpscenes.obstacles.sphere_obstacle import SphereObstacle
from mpscenes.goals.goal_composition import GoalComposition
from urdfenvs.urdf_common.urdf_env import UrdfEnv
from mpc_example import MpcExample
from robotmpcs.planner.visualizer import Visualizer
from robotmpcs.global_planner import globalPlanner

class BoxerMpcExample(MpcExample):

    def initialize_environment(self):
        self._visualizer = Visualizer()

        robots = [
            GenericDiffDriveRobot(
                urdf='boxer.urdf',
                mode=self._config['mpc']['control_mode'],
                actuated_wheels=["wheel_right_joint", "wheel_left_joint"],
                castor_wheels=["rotacastor_right_joint", "rotacastor_left_joint"],
                wheel_radius=0.08,
                wheel_distance=0.494,
                spawn_rotation=np.pi / 2,
            ),
        ]

        goal_dict = {
            "subgoal0": {
                "weight": 1.0,
                "is_primary_goal": True,
                "indices": [0, 1],
                "parent_link": 'origin',
                "child_link": 'ee_link',
                "desired_position": [6.2, -3.2],
                "epsilon": 0.4,
                "type": "staticSubGoal"
            }
        }
        self._goal = GoalComposition(name="goal1", content_dict=goal_dict)
        obst1Dict = {
            "type": "sphere",
            "geometry": {"position": [4.0, -1.5, 0.0], "radius": 1.0},
        }
        sphereObst1 = SphereObstacle(name="simpleSphere", content_dict=obst1Dict)
        self._obstacles = [sphereObst1]
        self._r_body = 0.6
        self._limits = np.array([
                [-10, 10],
                [-10, 10],
                [-10, 10],
        ])
        # self._limits_vel = np.array([ #todo add to config
        #         [(-4), 4],
        #         [(-10), 10],
        # ])
        self._limits_u = np.array([
                [-10, 10],
                [-10, 10],
        ])
        current_path = os.path.dirname(os.path.abspath(__file__))

        self._env: UrdfEnv = gym.make(
                'urdf-env-v0',
                render=self._render,
                robots=robots,
                dt=self._planner._config.time_step
            )
        for i in range(self._config['mpc']['time_horizon']):
            self._env.add_visualization(size=[self._r_body, 0.1])

    def run(self):
        q0 = np.median(self._limits, axis = 1)
        ob, *_ = self._env.reset(pos=q0)
        for obstacle in self._obstacles:
            self._env.add_obstacle(obstacle)
        self._env.add_goal(self._goal)

        # add sensor
        val = 40
        sensor = OccupancySensor(
            limits=np.array([[-5, 10], [-5, 10], [0, 50 / val]]),
            resolution=np.array([val + 1, val + 1, 5], dtype=int),
            interval=100,
            plotting_interval=100,
        )

        self._env.add_sensor(sensor, [0])
        self._env.set_spaces()

        global_planner = globalPlanner.GlobalPlanner(dim_pixels = sensor._resolution,
                                                     limits_low = sensor._limits.transpose()[0],
                                                     limits_high = sensor._limits.transpose()[1],
                                                     BOOL_PLOTTING=True)
        global_path = []

        n_steps = 1000
        for w in range(n_steps):
            q = ob['robot_0']['joint_state']['position']
            qdot = ob['robot_0']['joint_state']['velocity']
            vel = np.array((ob['robot_0']['joint_state']['forward_velocity'], qdot[2]), dtype=float)

            #at first step: compute global path:
            if w == 1:
                global_planner.get_occupancy_map(sensor)
                goal_pos = self._goal._config.subgoal0.desired_position + [0]
                global_path, _ = global_planner.get_global_path_astar(start_pos=q, goal_pos=goal_pos)
                global_planner.add_path_to_env(path_length=len(global_path), env=self._env)

            if len(global_path)>0:
                local_goal = global_planner.get_local_goal(q[0:2], global_path)
                self._planner.setGoal(goal_position=local_goal)
            action,output = self._planner.computeAction(q, qdot, vel)
            plan = []
            for key in output:
                plan.append(np.concatenate([output[key][:2],np.zeros(1)]))
            ob, *_ = self._env.step(action)
            if self.check_goal_reaching(ob):
                print("goal reached")
                break
            self._env.update_visualizations(plan+global_path)

    def check_goal_reaching(self, ob):
        primary_goal = self._goal.primary_goal()
        goal_dist = np.linalg.norm(ob['robot_0']['joint_state']['position'][:2] - primary_goal.position()) # todo remove hard coded dimension, replace it with fk instead
        if goal_dist <= primary_goal.epsilon():
            return True
        return False

def main():
    boxer_example = BoxerMpcExample(sys.argv[1])
    boxer_example.initialize_environment()
    boxer_example.set_mpc_parameter()
    boxer_example.run()


if __name__ == "__main__":
    main()
