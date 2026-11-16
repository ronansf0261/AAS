//20SFFACTORY COMMUNITY ROBOT FIRMWARE

//MAINTAINER: LEOYEUNG@20SFFACTORY
//CONTACT: yeung.kl.leo@gmail.com
//FORUM: www.facebook.com/groups/robotarm

//VERSION: V0.81

//VERSION HISTORY:
//   V0.31 WITH G92, M114, LOGGER, LIMIT_CHECK FUNCTIONS
//   V0.41 WITH DUAL SHANK LENGTH SUPPORT
//   V0.51 WITH SERVO GRIPPER
//   V0.61 WITH ARDUINO UNO OPTION
//   V0.71 WITH:
//       ESP32(WEMOS D1R32) WITH PS4 JOYSTICK CONTROL OPTION
//       COMMAND TO SET CUSTOM SPEED PROFILE 'M205 S0'
//       UNO OPTION WITH RAIL SUPPORT
//   V0.81 WITH WII REMOTE, JOYSTICK ADJUSTABLE SPEED MULTIPLIER


#include <Arduino.h>
#include <EEPROM.h>
//GENERAL CONFIG SETTINGS
#include "config.h"

#include "robotGeometry.h"
#include "interpolation.h"
#include "RampsStepper.h"
#include "queue.h"
#include "command.h"
#include "equipment.h"
#include "endstop.h"
#include "logger.h"
#include "fanControl.h"
#include "StepInterpolation.h"
#include "tracepath.h"

//INCLUDE CORRESPONDING GRIPPER MOTOR CLASS
#if GRIPPER == SERVO
  #include "servo_gripper.h"
#elif GRIPPER == BYJ
  #include "byj_gripper.h"
#endif

//DETERMINE PINOUTS & CONFIG TO USE SUBJECT TO BOARD_CHOICE
#if BOARD_CHOICE == UNO
  #include "pinout/pinout_uno.h"
#elif BOARD_CHOICE == WEMOSD1R32
  #include "pinout/pinout_wemosD1R32.h"
  #include "config_esp32.h"
#elif BOARD_CHOICE == MEGA2560
  #include "pinout/pinout.h"
#endif

//STEPPER OBJECTS
RampsStepper stepperHigher(X_STEP_PIN, X_DIR_PIN, X_ENABLE_PIN, INVERSE_X_STEPPER, MAIN_GEAR_TEETH, MOTOR_GEAR_TEETH, MICROSTEPS, STEPS_PER_REV);
RampsStepper stepperLower(Y_STEP_PIN, Y_DIR_PIN, Y_ENABLE_PIN, INVERSE_Y_STEPPER, MAIN_GEAR_TEETH, MOTOR_GEAR_TEETH, MICROSTEPS, STEPS_PER_REV);
//RampsStepper stepperRotate(Z_STEP_PIN, Z_DIR_PIN, Z_ENABLE_PIN, INVERSE_Z_STEPPER, MAIN_GEAR_TEETH, MOTOR_GEAR_TEETH, MICROSTEPS, STEPS_PER_REV);
RampsStepper stepperRotate(Z_STEP_PIN, Z_DIR_PIN, Z_ENABLE_PIN, INVERSE_Z_STEPPER, MAIN_GEAR_TEETH, MOTOR_GEAR_TEETH, MICROSTEPS, STEPS_PER_REV);

//CAL
bool wasFinished = true; 
bool setup_state = false;

long xSteps = 0;
long ySteps = 0;
long zSteps = 0;

int actualStepX = 0;
int actualStepY = 0;
int actualStepZ = 0;

int targetStepPosX = 0;
int targetStepPosY = 0;
int targetStepPosZ = 0;

int loaded_x = 0;
int loaded_y = 0;
int loaded_z = 0;

/*
int dx = 0;
int dy = 0;
int dz = 0;
*/

//RAIL OBJECTS
#if RAIL
  RampsStepper stepperRail(E0_STEP_PIN, E0_DIR_PIN, E0_ENABLE_PIN, INVERSE_E0_STEPPER, MAIN_GEAR_TEETH, MOTOR_GEAR_TEETH, MICROSTEPS, STEPS_PER_REV);
  #if BOARD_CHOICE == WEMOSD1R32 //PINSWAP REQIURED ON D1R32 DUE TO INSUFFICIENT DIGIAL PINS
    #define SERVO_PIN 23 // REDEFINE SERVO_PIN FOR RAIL // SHARE WITH Z_MIN_PIN
    Endstop endstopE0(E0_MIN_PIN, E0_DIR_PIN, E0_STEP_PIN, E0_ENABLE_PIN, E0_MIN_INPUT, E0_HOME_STEPS, HOME_DWELL, true);
  #else 
    Endstop endstopE0(E0_MIN_PIN, E0_DIR_PIN, E0_STEP_PIN, E0_ENABLE_PIN, E0_MIN_INPUT, E0_HOME_STEPS, HOME_DWELL, false);
  #endif
#endif

//ENDSTOP OBJECTS
Endstop endstopE0(E0_MIN_PIN, E0_DIR_PIN, E0_STEP_PIN, E0_ENABLE_PIN, E0_MIN_INPUT, E0_HOME_STEPS, HOME_DWELL, false);
Endstop endstopX(X_MIN_PIN, X_DIR_PIN, X_STEP_PIN, X_ENABLE_PIN, X_MIN_INPUT, X_HOME_STEPS, HOME_DWELL, false);
Endstop endstopY(Y_MIN_PIN, Y_DIR_PIN, Y_STEP_PIN, Y_ENABLE_PIN, Y_MIN_INPUT, Y_HOME_STEPS, HOME_DWELL, false);
#if BOARD_CHOICE == WEMOSD1R32
  Endstop endstopZ(Z_MIN_PIN, Z_DIR_PIN, Z_STEP_PIN, Z_ENABLE_PIN, Z_MIN_INPUT, Z_HOME_STEPS, HOME_DWELL, true);
#else
  Endstop endstopZ(Z_MIN_PIN, Z_DIR_PIN, Z_STEP_PIN, Z_ENABLE_PIN, Z_MIN_INPUT, Z_HOME_STEPS, HOME_DWELL, false);
#endif
//EQUIPMENT OBJECTS
#if GRIPPER == SERVO
  Servo_Gripper servo_gripper(SERVO_PIN, SERVO_GRIP_DEGREE, SERVO_UNGRIP_DEGREE);
#elif GRIPPER == BYJ
  BYJ_Gripper byj_gripper(BYJ_PIN_0, BYJ_PIN_1, BYJ_PIN_2, BYJ_PIN_3, BYJ_GRIP_STEPS);
#endif
Equipment laser(LASER_PIN);
Equipment pump(PUMP_PIN);
Equipment led(LED_PIN);
FanControl fan(FAN_PIN, FAN_DELAY);

//EXECUTION & COMMAND OBJECTS
RobotGeometry geometry(END_EFFECTOR_OFFSET, LOW_SHANK_LENGTH, HIGH_SHANK_LENGTH);
Interpolation interpolator;
StepInterpolation step_interpolator;

Queue<Cmd> queue(QUEUE_SIZE);
Command command;
Tracepath trace;

//PS4 CONTROLLER OBJECT FOR ESP32
#if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == DUALSHOCK4
  #include "controller_ps4.h"
  Controller_PS4 controller_ps4(PS4_MAC);
#endif
#if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == WIIMOTE
  #include "controller_wiimote.h"
  Controller_Wiimote controller_wiimote;
#endif

void setup()
{
  Serial.begin(BAUD);
  #if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == DUALSHOCK4
    controller_ps4.setup();
  #endif
  #if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == WIIMOTE
    controller_wiimote.setup();
  #endif
  stepperHigher.setPositionRad(PI / 2.0); // 90°
  stepperLower.setPositionRad(0);         // 0°
  stepperRotate.setPositionRad(0);        // 0°
  #if RAIL
  stepperRail.setPosition(0);
  #endif
  step_interpolator.setCurrentPos(0, 0, 0, 0);
  if (HOME_ON_BOOT) { //HOME DURING SETUP() IF HOME_ON_BOOT ENABLED
    homeSequence(); 
    Logger::logINFO("ROBOT ONLINE");
  } else {
    setStepperEnable(false); //ROBOT ADJUSTABLE BY HAND AFTER TURNING ON
    if (HOME_X_STEPPER && HOME_Y_STEPPER && !HOME_Z_STEPPER){
      Logger::logINFO("ROBOT ONLINE");
      Logger::logINFO("ROTATE ROBOT TO FACE FRONT CENTRE & SEND G28 TO CALIBRATE");
    }
    if (HOME_X_STEPPER && HOME_Y_STEPPER && HOME_Z_STEPPER){
      Logger::logINFO("ROBOT ONLINE");
      Logger::logINFO("SEND G28 TO CALIBRATE");
    }
    if (!HOME_X_STEPPER && !HOME_Y_STEPPER){
      Logger::logINFO("ROBOT ONLINE");
      Logger::logINFO("HOME ROBOT MANUALLY & SEND G28 TO CALIBRATE");
    }
  }

  EEPROM.get(0, loaded_x);
  EEPROM.get(sizeof(loaded_x), loaded_y);
  EEPROM.get(sizeof(loaded_x) + sizeof(loaded_y), loaded_z);
  if (loaded_x > 2000 || loaded_x < -2000) {
    loaded_x = 0;
    EEPROM.put(0, loaded_x);
  }
  if (loaded_y > 2000 || loaded_y < -2000) {
    loaded_y = 0;
    EEPROM.put(sizeof(loaded_x), loaded_y);
  }
  if (loaded_z > 2000 || loaded_z < -2000) {
    loaded_z = 0;
    EEPROM.put(sizeof(loaded_x) + sizeof(loaded_y), loaded_z);
  }

  interpolator.setInterpolation(INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0, INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0);
}

void loop() {
  if(setup_state){
    actualStepX = stepperHigher.getActualStep();
    actualStepY = stepperLower.getActualStep();
    actualStepZ = stepperRotate.getActualStep();

    step_interpolator.setCurrentPos(actualStepX, actualStepY, actualStepZ, 0);
    step_interpolator.updateActualPosition();

    xSteps = step_interpolator.getXSteps();
    ySteps = step_interpolator.getYSteps();
    zSteps = step_interpolator.getZSteps();

    // Nao remover o log abaixo
    Logger::logINFO("MOVED X: " + String(actualStepX) + " MOVED Y: " + String(actualStepY) + " MOVED Z: " + String(actualStepZ));

    stepperHigher.stepRelative(xSteps);
    stepperLower.stepRelative(ySteps);
    stepperRotate.stepRelative(zSteps);
  }
  else{
    interpolator.updateActualPosition();
    trace.updateActualTracePosition(interpolator.getXPosmm(), interpolator.getYPosmm(), interpolator.getZPosmm());
    //chamada para rastrear e sendo o caso enviar Logger pela serial
    geometry.set(interpolator.getXPosmm(), interpolator.getYPosmm(), interpolator.getZPosmm());
    stepperRotate.stepToPositionRad(geometry.getRotRad());
    stepperLower.stepToPositionRad(geometry.getLowRad());
    stepperHigher.stepToPositionRad(geometry.getHighRad());
  }
  
  #if RAIL
    stepperRail.stepToPositionMM(interpolator.getEPosmm(), STEPS_PER_MM_RAIL);
  #endif
  stepperRotate.update();
  stepperLower.update();
  stepperHigher.update();
  #if RAIL
    stepperRail.update();
  #endif
  fan.update();

  if (!queue.isFull()) {
    if (command.handleGcode()) {
      queue.push(command.getCmd());      
    }
    
  }
  if ((!queue.isEmpty()) && interpolator.isFinished()) {
    //trace.updateEndTracePosition(interpolator.getXPosmm(), interpolator.getYPosmm(), interpolator.getZPosmm());
    executeCommand(queue.pop());
    
  }

  if(interpolator.isFinished()) {
    
    trace.updateEndTracePosition(interpolator.getXPosmm(), interpolator.getYPosmm(), interpolator.getZPosmm());
    
  }

 // bool isCurrentlyFinished = interpolator.isFinished();
      
      //if (!wasFinished && isCurrentlyFinished) {
     //   Serial.println(PRINT_REPLY_MSG); 
     // }
     // wasFinished = isCurrentlyFinished;



  if (millis() % 500 < 250) {
    led.cmdOn();
  }
  else {
    led.cmdOff();
  }

  #if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == DUALSHOCK4
    ps4_controller_loop();
  #endif
  #if BOARD_CHOICE == WEMOSD1R32 && ESP32_JOYSTICK == WIIMOTE
    wiimote_controller_loop();
  #endif
}

void executeCommand(Cmd cmd) {

  if (cmd.id == -1) {
    printErr();
    return;
  }

  if (cmd.id == 'G') {
    switch (cmd.num) {
    case 0:
    case 1:
      fan.enable(true);
      Point posoffset;
      posoffset = interpolator.getPosOffset();      
      cmdMove(cmd, interpolator.getPosmm(), posoffset, command.isRelativeCoord);
      interpolator.setInterpolation(cmd.valueX, cmd.valueY, cmd.valueZ, cmd.valueE, cmd.valueF);
      Logger::logINFO("LINEAR MOVE: [X:" + String(cmd.valueX-posoffset.xmm) + " Y:" + String(cmd.valueY-posoffset.ymm) + " Z:" + String(cmd.valueZ-posoffset.zmm) + " E:" + String(cmd.valueE-posoffset.emm)+"]");
     
     
      break;
    case 4: cmdDwell(cmd);
          if (PRINT_REPLY) {
            Serial.println(PRINT_REPLY_MSG);
           } 
      break;
    case 28: 
      if (BOARD_CHOICE == UNO || BOARD_CHOICE == WEMOSD1R32){
        homeSequence_UNO();
        break;
      } else {
        homeSequence();
        break;
      }
    case 90: command.cmdToAbsolute(); break; // ABSOLUTE COORDINATE MODE
    case 91: command.cmdToRelative(); break; // RELATIVE COORDINATE MODE
    case 92: 
      interpolator.resetPosOffset();
      cmdMove(cmd, interpolator.getPosmm(), interpolator.getPosOffset(), false);
      interpolator.setPosOffset(cmd.valueX, cmd.valueY, cmd.valueZ, cmd.valueE);
      break;
    case 93:
      if (isnan(cmd.valueX) & isnan(cmd.valueY) & isnan(cmd.valueZ)){
        if(setup_state){
          setup_state = false;
          Logger::logINFO("SETUP MODE OFF");

          actualStepX = stepperHigher.getActualStep();
          actualStepY = stepperLower.getActualStep();
          actualStepZ = stepperRotate.getActualStep();

          EEPROM.get(0, loaded_x);
          EEPROM.get(sizeof(loaded_x), loaded_y);
          EEPROM.get(sizeof(loaded_x) + sizeof(loaded_y), loaded_z);

          EEPROM.put(0, (loaded_x + actualStepX));
          EEPROM.put(sizeof(actualStepX), (loaded_y + actualStepY));
          EEPROM.put(sizeof(actualStepX) + sizeof(actualStepY), (loaded_z + actualStepZ));
        }
        else{
          setup_state = true;
          Logger::logINFO("SETUP MODE ON");

          EEPROM.get(0, loaded_x);
          EEPROM.get(sizeof(loaded_x), loaded_y);
          EEPROM.get(sizeof(loaded_x) + sizeof(loaded_y), loaded_z);

          Logger::logINFO("LOADED X: " + String(loaded_x) + " Y: " + String(loaded_y) + " Z: " + String(loaded_z));

        }
      }
      
      if (setup_state) {
        targetStepPosX = stepperHigher.getActualStep();
        targetStepPosY = stepperLower.getActualStep();
        targetStepPosZ = stepperRotate.getActualStep();

        if (!isnan(cmd.valueX)) {
          targetStepPosX = (int) cmd.valueX;
          //int targetStepPosX = (int) cmd.valueX;
        }

        if (!isnan(cmd.valueY)) {
          targetStepPosY = (int) cmd.valueY;
          //int targetStepPosY = (int) cmd.valueY;
        }

        if (!isnan(cmd.valueZ)) {
          targetStepPosZ = (int) cmd.valueZ;
          //int targetStepPosZ = (int) cmd.valueZ;
        }

        step_interpolator.setTargetPos(targetStepPosX, targetStepPosY, targetStepPosZ, 0);

      }
      break;
    default: printErr();
    }
  }
  else if (cmd.id == 'M') {
    
    switch (cmd.num) {
    case 1: pump.cmdOn(); break;
    case 2: pump.cmdOff(); break;
    case 3: 
      #if GRIPPER == BYJ
        byj_gripper.cmdOn(); 
        break;
      #elif GRIPPER == SERVO
         if (cmd.valueS < 180) {     
                servo_gripper.cmdOn(cmd.valueS);
            } else {
               
                servo_gripper.cmdOn();
            }
        
            break;
      #endif
      
    case 5:
      #if GRIPPER == BYJ
        byj_gripper.cmdOff();
         break;
      #elif GRIPPER == SERVO
         if (cmd.valueS > 0) {
                // Comando `M5S20` ou similar: define o servo com um ângulo específico
                servo_gripper.cmdOff(cmd.valueS);
            } else {
                // Comando `M5`: usa o ângulo de soltura padrão
                servo_gripper.cmdOff();
            }
            break;
      #endif
    case 6: laser.cmdOn(); break;
    case 7: laser.cmdOff(); break;
    case 17: setStepperEnable(true); break;
    case 18: setStepperEnable(false); break;
    case 106: fan.enable(true); break;
    case 107: fan.enable(false); break;
    case 114: command.cmdGetPosition(interpolator.getPosmm(), interpolator.getPosOffset(), stepperHigher.getPosition(), stepperLower.getPosition(), stepperRotate.getPosition()); break;// Return the current positions of all axis 
    case 119: {
      String endstopMsg = "ENDSTOP: [X:";
      endstopMsg += String(endstopX.state());
      endstopMsg += " Y:";
      endstopMsg += String(endstopY.state());
      endstopMsg += " Z:";
      endstopMsg += String(endstopZ.state());
      #if RAIL
      endstopMsg += " E:";
      endstopMsg += String(endstopE0.state());
      #endif
      endstopMsg += "]";
      //ORIGINAL LOG STRING UNDESIRABLE FOR UNO PROCESSING
      //Logger::logINFO("ENDSTOP STATE: [UPPER_SHANK(X):"+String(endstopX.state())+" LOWER_SHANK(Y):"+String(endstopY.state())+" ROTATE_GEAR(Z):"+String(endstopZ.state())+"]");
      Logger::logINFO(endstopMsg);
      break;}
    case 205:
      interpolator.setSpeedProfile(cmd.valueS); 
      Logger::logINFO("SPEED PROFILE: [" + String(interpolator.speed_profile) + "]");
      break;
    case 300://seta LogTrace  Usage: M300 S2 (indica passo de 2mm)
      trace.enableTrace(cmd.valueS);
      trace.enableLogData();
      Logger::logINFO("TRACE LOG ENABLED WITH GAP: " + String(trace.getInterval()));
      break;
    case 301://reseta LogTrace  Usage: M300 S2 (indica passo de 2mm)
      trace.disableLogData();
      Logger::logINFO("TRACE LOG DISABLED");
      break;
    default: printErr();
    }
  }
  else {
    printErr();
  }
}

void setStepperEnable(bool enable){
  stepperRotate.enable(enable);
  stepperLower.enable(enable);
  stepperHigher.enable(enable);
  #if RAIL
    stepperRail.enable(enable);
  #endif
  fan.enable(enable);
}

void homeSequence(){
  EEPROM.get(0, loaded_x);
  EEPROM.get(sizeof(loaded_x), loaded_y);
  EEPROM.get(sizeof(loaded_x) + sizeof(loaded_y), loaded_z);
  endstopX.setStepOffset(X_HOME_STEPS + loaded_x);
  endstopY.setStepOffset(Y_HOME_STEPS + loaded_y);
  endstopZ.setStepOffset(Z_HOME_STEPS - loaded_z);

  setStepperEnable(false);
  fan.enable(true);
  if (HOME_Y_STEPPER && HOME_X_STEPPER){
    endstopY.home(!INVERSE_Y_STEPPER);
    endstopX.home(!INVERSE_X_STEPPER);
  } else {
    setStepperEnable(true);
    endstopY.homeOffset(!INVERSE_Y_STEPPER);
    endstopX.homeOffset(!INVERSE_X_STEPPER);
  }
  if (HOME_Z_STEPPER){
    endstopZ.home(INVERSE_Z_STEPPER);
  }
  #if RAIL
    if (HOME_E0_STEPPER){
      endstopE0.home(!INVERSE_E0_STEPPER);
    }
  #endif
  interpolator.setInterpolation(INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0, INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0);
  Logger::logINFO("HOMING COMPLETE");
}

//DUE TO UNO CNC SHIELD LIMIT, 1 EN PIN SERVES 3 MOTORS, HENCE DIFFERENT HOMESEQUENCE IS REQUIRED
void homeSequence_UNO(){
  #if GRIPPER == SERVO
  if (servo_gripper.readDegree() != SERVO_UNGRIP_DEGREE){
    servo_gripper.cmdOff();
  }
  #endif
  if (HOME_Y_STEPPER && HOME_X_STEPPER){
    while (!endstopY.state() || !endstopX.state()){
      endstopY.oneStepToEndstop(!INVERSE_Y_STEPPER);
      endstopX.oneStepToEndstop(!INVERSE_X_STEPPER);
    }
    endstopY.homeOffset(!INVERSE_Y_STEPPER);
    endstopX.homeOffset(!INVERSE_X_STEPPER);
  } else {
    setStepperEnable(true);
    endstopY.homeOffset(!INVERSE_Y_STEPPER);
    endstopX.homeOffset(!INVERSE_X_STEPPER);
  }
  if (HOME_Z_STEPPER){
    endstopZ.home(INVERSE_Z_STEPPER); //INDICATE STEPPER HOMING DIRECDTION
  }
  #if RAIL
    if (HOME_E0_STEPPER){
      endstopE0.home(!INVERSE_E0_STEPPER);
    }
  #endif
  interpolator.setInterpolation(INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0, INITIAL_X, INITIAL_Y, INITIAL_Z, INITIAL_E0);
  Logger::logINFO("HOMING COMPLETE");
}
