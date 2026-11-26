# Wheeled robots: SimReady_Metadata.mobile

proofmass-check runs STAND, DRIVE, TURN and STEER on an asset whose root layer describes its wheels.
The description is a dictionary in the root layer's `customLayerData`, at
`SimReady_Metadata` → `mobile`. Proofmass's build writes it. Any other maker can write it too.

Without this dictionary, proofmass-check treats a wheeled robot like any other asset: on the floor,
with DROP and the drive checks, and without the wheeled checks. When its joints look like wheels (no
limits, a near horizontal axis, a velocity drive), the run says so in a note, so that a pass is not read
as a pass of the wheeled checks.

## A robot from another maker

`proofmass-check describe-wheels robot.usd` proposes the description from the USD, as JSON, and
`--write` writes it in `robot_mobile.usda` next to the robot. That layer sublayers the robot, whose
own files do not change: run the checks on it. The GUI's inspector shows the same proposal.

- A wheel is a revolute joint without limits, about an axis within about 17 deg of horizontal. It
  is driven when it has a velocity drive. Its radius and centre come from a cylinder about its
  joint axis that holds the colliders of the body it moves.
- The side is the sign of the wheel's y. The spin is +1 when the joint axis points left (+Y): a
  positive speed then rolls the wheel toward +X.
- Two driven wheels make a differential robot, more make a skid-steer one. The radius, track and
  axle centre come from the driven wheels.
- It is a proposal. Check that a positive speed of each wheel with spin +1 rolls the robot forward,
  and that the front faces +X: a wheel whose joint axis is the wrong way round gets spin -1 and
  looks right. A note says when the wheels do not stand on z = 0.
- An Ackermann robot is not proposed: its steering range and the sign of each steering joint must
  come from its maker.

## Conventions

- The robot's front faces +X, left is +Y, up is +Z (ROS REP-103, as Isaac Sim's robots).
- The wheels stand on z = 0 in the file.
- Lengths in metres. Steering limits in degrees, as USD gives joint limits. Wheel speed limits in rad/s.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `drive` | string | `differential`, `skid_steer` or `ackermann` |
| `radius` | float | mean radius of the driven wheels, m |
| `track` | float | distance between the left and the right driven wheels, m |
| `axle_center` | [x, y] | centre of the driven axle, m. The robot turns about this point. |
| `wheels` | dictionary | one entry per wheel joint, by joint name (below) |
| `steering` | dictionary | Ackermann only: one entry per steering joint, by joint name (below) |
| `wheelbase` | float | Ackermann only: from the driven axle to the steering joints along X, m |
| `front_track` | float | Ackermann only: distance between the two steering joints, m |

A wheel:

| Field | Type | Meaning |
|---|---|---|
| `side` | string | `left`, `right` or `centre` |
| `driven` | bool | true when its joint has a velocity drive |
| `radius` | float | m |
| `spin` | +1 or −1 | the sign of the joint speed that rolls the robot forward |
| `center` | [x, y, z] | centre of the wheel in the file, m |
| `max_speed` | float | optional: the joint's speed limit, rad/s |

A steering joint (a revolute joint about Z with a wheel below it):

| Field | Type | Meaning |
|---|---|---|
| `side` | string | `left` or `right` |
| `x`, `y` | float | position of the joint, m |
| `sign` | +1 or −1 | +1 when a positive angle turns the wheel left |
| `lower`, `upper` | float | the joint's limits, degrees |

## Example

```usda
#usda 1.0
(
    customLayerData = {
        dictionary SimReady_Metadata = {
            dictionary mobile = {
                string drive = "differential"
                double radius = 0.1
                double track = 0.4
                double[] axle_center = [0, 0]
                dictionary wheels = {
                    dictionary left_wheel_joint = {
                        string side = "left"
                        bool driven = 1
                        double radius = 0.1
                        int spin = 1
                        double[] center = [0, 0.2, 0.1]
                    }
                    dictionary right_wheel_joint = {
                        string side = "right"
                        bool driven = 1
                        double radius = 0.1
                        int spin = 1
                        double[] center = [0, -0.2, 0.1]
                    }
                }
            }
        }
    }
    defaultPrim = "rover"
)
```
