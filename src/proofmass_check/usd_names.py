# SPDX-FileCopyrightText: 2026 Paweł Kikta
# SPDX-License-Identifier: Apache-2.0
"""USD attribute names that do not come from the UsdPhysics schema.

The reader uses the UsdPhysics Python API for standard physics data. The names below come from
the PhysX, MuJoCo and Newton schemas and from NVIDIA's SimReady rules. These change between engine
versions more often than UsdPhysics does, so each one is written here once, with its source.
"""

# PhysicsJointStateAPI: the rest position of a joint. <dof> is "angular", "linear" or a D6 axis
# such as "rotX". Degrees for an angle, metres for a distance.
JOINT_STATE_POSITION = "state:{dof}:physics:position"

# PhysX (Isaac Sim): the speed limit of a joint, deg/s for a revolute joint, m/s for a prismatic one.
PHYSX_MAX_JOINT_VELOCITY = "physxJoint:maxJointVelocity"

# PhysX mimic joint, one per axis: physxMimicJoint:<axis>:referenceJoint (a relationship to the
# leader) and physxMimicJoint:<axis>:gearing. PhysX keeps follower + gearing x leader = 0.
PHYSX_MIMIC_PREFIX = "physxMimicJoint:"
PHYSX_MIMIC_REFERENCE = ":referenceJoint"
PHYSX_MIMIC_GEARING = ":gearing"

# MuJoCo schema (MjcEqualityJointAPI): follower = coef1 x leader.
MJC_MIMIC_TARGET = "mjc:target"
MJC_MIMIC_COEF = "mjc:coef1"

# MuJoCo schema (MjcActuator prim): the joint it acts on, and MuJoCo's general actuator model.
# The force is gainPrm[0] x control + biasPrm[0] + biasPrm[1] x position + biasPrm[2] x speed.
MJC_ACTUATOR = "MjcActuator"
MJC_ACTUATOR_TARGET = "mjc:target"
MJC_ACTUATOR_GAIN_TYPE = "mjc:gainType"
MJC_ACTUATOR_BIAS_TYPE = "mjc:biasType"
MJC_ACTUATOR_DYN_TYPE = "mjc:dynType"
MJC_ACTUATOR_GEAR = "mjc:gear"
MJC_ACTUATOR_GAIN = "mjc:gainPrm"
MJC_ACTUATOR_BIAS = "mjc:biasPrm"
MJC_ACTUATOR_FORCE_MIN = "mjc:forceRange:min"  # N, or N m
MJC_ACTUATOR_FORCE_MAX = "mjc:forceRange:max"

# Newton schema (NewtonMimicAPI): follower = coef1 x leader, unless mimicEnabled is false.
NEWTON_MIMIC_JOINT = "newton:mimicJoint"
NEWTON_MIMIC_COEF = "newton:mimicCoef1"
NEWTON_MIMIC_ENABLED = "newton:mimicEnabled"

# The name Isaac Sim gives one axis of a D6 joint (its MJCF importer writes it).
D6_AXIS_NAME = "mjcf:{axis}:name"

# NVIDIA SimReady gripper rules GR.001 to GR.004: attributes of the gripper site prim, and the
# names of two BasisCurves child prims that draw the approach direction and the grip line.
GRIPPER_MAX_OPENING = "gripper_maxOpening"  # m
GRIPPER_MAX_PAYLOAD = "gripper_maxPayload"  # kg
GRIPPER_FORWARD_AXIS = "gripper_forward_axis"
GRIPPER_GRIP_LINE = "gripper_grip_line"

# Wheeled robots: a dictionary in the root layer's customLayerData, at SimReady_Metadata -> mobile.
# docs/wheeled-robots.md describes its fields.
LAYER_METADATA = "SimReady_Metadata"
LAYER_METADATA_MOBILE = "mobile"
