"""One AMR agent: VDA 5050 bridge + order executor + primitive controller (+ optional fake robot).

Every behaviour number (speeds, ramps, tolerances, state period, battery, fake-robot plant) comes from ONE
robot profile that all four nodes resolve the same way (amr_agent/profile.py):
  config/models/<model>.yaml  <  profile_file:=<yaml|json>  <  profile_overrides:='<JSON>'
profile_file / profile_overrides accept the BE `amr` block keys as-is (speed_empty, speed_loaded, consumption,
battery, charge_time, charge_threshold, capacity, tote_units) and any profile key; unknown keys abort the launch.

  ros2 launch amr_agent agent.launch.py serial:=amr01 mqtt_host:=localhost fake_robot:=true
  # BE-given parameters (what sim-runner sends from scenario.amr):
  ros2 launch amr_agent agent.launch.py serial:=amr01 fake_robot:=true profile_overrides:='{"speed_empty": 1.2, "consumption": 0.02}'
  # same thing from a file (config/overrides.example.yaml is the BE example):
  ros2 launch amr_agent agent.launch.py serial:=amr01 fake_robot:=true profile_file:=/path/amr.yaml
  # with an EMQX account (3_FMS/infra/emqx — username = serial):
  MQTT_PW=… ros2 launch amr_agent agent.launch.py serial:=amr01 mqtt_username:=amr01 mqtt_password:=$MQTT_PW fake_robot:=true
  # against Isaac WSIM_N mode (namespaced /amr01/odom …): nothing to remap
  ros2 launch amr_agent agent.launch.py serial:=amr01 mqtt_username:=amr01 mqtt_password:=$MQTT_PW pose_source:=odom use_sim_time:=true
  # against single-robot Isaac (flat /odom, /cmd_vel):
  ros2 launch amr_agent agent.launch.py serial:=amr01 flat_topics:=true pose_source:=odom
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

ARGS = ("serial", "manufacturer", "map_id", "mqtt_host", "mqtt_port", "mqtt_username", "mqtt_password",
        "model", "profile_file", "profile_overrides", "pose_source", "fake_robot", "flat_topics",
        "fake_x", "fake_y", "fake_yaw", "use_sim_time")


def _truthy(s: str) -> bool:
    return s.lower() in ("1", "true", "yes")


def _nodes(context, *_args, **_kwargs):
    cfg = {k: LaunchConfiguration(k).perform(context) for k in ARGS}
    ns = cfg["serial"]
    remaps = [("odom", "/odom"), ("cmd_vel", "/cmd_vel"), ("amcl_pose", "/amcl_pose")] if _truthy(cfg["flat_topics"]) else []
    # 프로파일 입력은 네 노드가 똑같이 받는다 — 각자 같은 규칙으로 풀어 같은 값을 본다
    common = {"serial": cfg["serial"], "manufacturer": cfg["manufacturer"], "use_sim_time": _truthy(cfg["use_sim_time"]),
              "model": cfg["model"], "profile_file": cfg["profile_file"], "profile_overrides": cfg["profile_overrides"]}
    nodes = [
        Node(package="amr_agent", executable="vda5050_bridge", namespace=ns, output="screen",
             parameters=[common, {"mqtt_host": cfg["mqtt_host"], "mqtt_port": int(cfg["mqtt_port"]),
                                  "mqtt_username": cfg["mqtt_username"], "mqtt_password": cfg["mqtt_password"]}]),
        Node(package="amr_agent", executable="order_executor", namespace=ns, output="screen",
             parameters=[common, {"map_id": cfg["map_id"], "pose_source": cfg["pose_source"]}],
             remappings=remaps),
        Node(package="amr_agent", executable="primitive_controller", namespace=ns, output="screen",
             parameters=[common, {"pose_source": cfg["pose_source"]}], remappings=remaps),
    ]
    if _truthy(cfg["fake_robot"]):
        nodes.append(Node(package="amr_agent", executable="fake_robot", namespace=ns, output="screen",
                          parameters=[common, {"x": float(cfg["fake_x"]), "y": float(cfg["fake_y"]),
                                               "yaw": float(cfg["fake_yaw"])}], remappings=remaps))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("serial", default_value="amr01"),
        DeclareLaunchArgument("manufacturer", default_value="idealworks", description="VDA manufacturer = per model (contract §1-5)"),
        DeclareLaunchArgument("map_id", default_value="wallA"),
        DeclareLaunchArgument("mqtt_host", default_value="localhost"),
        DeclareLaunchArgument("mqtt_port", default_value="1883"),
        DeclareLaunchArgument("mqtt_username", default_value="", description="EMQX account = serial (empty = anonymous)"),
        DeclareLaunchArgument("mqtt_password", default_value=""),
        DeclareLaunchArgument("model", default_value="iw_hub", description="config/models/<model>.yaml = factory profile"),
        DeclareLaunchArgument("profile_file", default_value="",
                              description="yaml|json overriding the profile — BE amr keys or profile keys"),
        DeclareLaunchArgument("profile_overrides", default_value="",
                              description="JSON string overriding the profile (wins over profile_file)"),
        DeclareLaunchArgument("pose_source", default_value="odom", description="odom | amcl"),
        DeclareLaunchArgument("fake_robot", default_value="false"),
        DeclareLaunchArgument("flat_topics", default_value="false",
                              description="remap odom/cmd_vel/amcl_pose to the global topics Isaac uses"),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("fake_x", default_value="0.0"),
        DeclareLaunchArgument("fake_y", default_value="0.0"),
        DeclareLaunchArgument("fake_yaw", default_value="0.0"),
        OpaqueFunction(function=_nodes),
    ])
