#!/usr/bin/env python3
import gc
from cereal import car
from common.realtime import set_realtime_priority
from common.params import Params
import cereal.messaging as messaging
from selfdrive.controls.lib.events import Events
from selfdrive.monitoring.driver_monitor import DriverStatus, MAX_TERMINAL_ALERTS, MAX_TERMINAL_DURATION
from selfdrive.locationd.calibration_helpers import Calibration
from common.realtime import DT_DMON
from common.realtime import sec_since_boot
import time


def dmonitoringd_thread(sm=None, pm=None):
  gc.disable()
  set_realtime_priority(53)

  # Pub/Sub Sockets
  if pm is None:
    pm = messaging.PubMaster(['dMonitoringState'])

  if sm is None:
    sm = messaging.SubMaster(['dragonConf', 'driverState', 'liveCalibration', 'carState', 'model'])

  params = Params()

  driver_status = DriverStatus()
  is_rhd = params.get("IsRHD")
  driver_status.is_rhd_region = is_rhd == b"1"
  driver_status.is_rhd_region_checked = is_rhd is not None

  sm['liveCalibration'].calStatus = Calibration.INVALID
  sm['liveCalibration'].rpyCalib = [0, 0, 0]
  sm['carState'].vEgo = 0.
  sm['carState'].cruiseState.enabled = False
  sm['carState'].cruiseState.speed = 0.
  sm['carState'].buttonEvents = []
  sm['carState'].steeringPressed = False
  sm['carState'].gasPressed = False
  sm['carState'].brakePressed = False
  sm['carState'].standstill = True

  v_cruise_last = 0
  driver_engaged = False
  offroad = params.get("IsOffroad") == b"1"

  # dp
  # sm['dragonConf'].dpDriverMonitor = True
  # sm['dragonConf'].dpSteeringMonitor = True
  # sm['dragonConf'].dpSteeringMonitorTimer = 70

  # 10Hz <- dmonitoringmodeld
  while True:
    start_time = sec_since_boot()
    sm.update()

    # dp
    # if not sm['dragonConf'].dpDriverMonitor:
    #   driver_status.active_monitoring_mode = False
    #   driver_status.face_detected = False
    #   driver_status.threshold_pre = 15. / sm['dragonConf'].dpSteeringMonitorTimer
    #   driver_status.threshold_prompt = 6. / sm['dragonConf'].dpSteeringMonitorTimer
    #   driver_status.step_change = DT_DMON / sm['dragonConf'].dpSteeringMonitorTimer
    #   if not sm['dragonConf'].dpSteeringMonitor:
    #     driver_status.awareness = 1.
    #     driver_status.awareness_active = 1.
    #     driver_status.awareness_passive = 1.
    #     driver_status.terminal_alert_cnt = 0
    #     driver_status.terminal_time = 0

    # Get interaction
    if sm.updated['carState']:
      v_cruise = sm['carState'].cruiseState.speed
      driver_engaged = len(sm['carState'].buttonEvents) > 0 or \
                        v_cruise != v_cruise_last or \
                        sm['carState'].steeringPressed or \
                        sm['carState'].gasPressed or \
                        sm['carState'].brakePressed
      if driver_engaged:
        driver_status.update(Events(), True, sm['carState'].cruiseState.enabled, sm['carState'].standstill)
      v_cruise_last = v_cruise

    # Get model meta
    if sm.updated['model']:
      driver_status.set_policy(sm['model'])

    # Get data from dmonitoringmodeld
    if sm.updated['driverState']:
      events = Events()
      if True:#sm['dragonConf'].dpDriverMonitor:
        driver_status.get_pose(sm['driverState'], sm['liveCalibration'].rpyCalib, sm['carState'].vEgo, sm['carState'].cruiseState.enabled)

      # Block engaging after max number of distrations
      if driver_status.terminal_alert_cnt >= MAX_TERMINAL_ALERTS or driver_status.terminal_time >= MAX_TERMINAL_DURATION:
        events.add(car.CarEvent.EventName.tooDistracted)

      # Update events from driver state
      driver_status.update(events, driver_engaged, sm['carState'].cruiseState.enabled, sm['carState'].standstill)

      # build dMonitoringState packet
      dat = messaging.new_message('dMonitoringState')
      dat.dMonitoringState = {
        "events": events.to_msg(),
        "faceDetected": driver_status.face_detected,
        "isDistracted": driver_status.driver_distracted,
        "awarenessStatus": driver_status.awareness,
        "isRHD": driver_status.is_rhd_region,
        "rhdChecked": driver_status.is_rhd_region_checked,
        "posePitchOffset": driver_status.pose.pitch_offseter.filtered_stat.mean(),
        "posePitchValidCount": driver_status.pose.pitch_offseter.filtered_stat.n,
        "poseYawOffset": driver_status.pose.yaw_offseter.filtered_stat.mean(),
        "poseYawValidCount": driver_status.pose.yaw_offseter.filtered_stat.n,
        "stepChange": driver_status.step_change,
        "awarenessActive": driver_status.awareness_active,
        "awarenessPassive": driver_status.awareness_passive,
        "isLowStd": driver_status.pose.low_std,
        "hiStdCount": driver_status.hi_stds,
        "isPreview": offroad,
      }
      pm.send('dMonitoringState', dat)
    diff = sec_since_boot() - start_time
    if diff < 0.1:
      time.sleep(0.1-diff)

def main(sm=None, pm=None):
  dmonitoringd_thread(sm, pm)

if __name__ == '__main__':
  main()
