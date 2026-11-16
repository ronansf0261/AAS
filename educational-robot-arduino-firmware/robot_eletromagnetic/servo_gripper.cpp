#include "servo_gripper.h"
#include "config.h"

#include <Arduino.h>

#if BOARD_CHOICE == WEMOSD1R32
  #include <ESP32Servo.h>
#else 
  #include <Servo.h>
#endif

Servo_Gripper::Servo_Gripper(int pin, float grip_degree, float ungrip_degree) {
  servo_pin = pin;
  servo_grip_deg = grip_degree;
  servo_ungrip_deg = ungrip_degree;
  Servo servo_motor;
}

void Servo_Gripper::cmdOn(float angle) {
  servo_motor.attach(servo_pin);
  delayMicroseconds(10);
  servo_motor.write((angle >= 0 ) ? angle : servo_grip_deg);  // Usa o ângulo `S` ou o padrão
  delay(300);
}

void Servo_Gripper::cmdOff(float angle) {
  servo_motor.write((angle >= 0 ) ? angle : servo_ungrip_deg);  // Usa o ângulo `S` ou o padrão
  delay(300);
  servo_motor.detach();
  delayMicroseconds(50);
}

float Servo_Gripper::readDegree() {
  float servo_current_degree = servo_motor.read();
  return servo_current_degree;
}

bool Servo_Gripper::isOn() {
  float servo_current_degree = servo_motor.read();
  return (servo_current_degree == servo_grip_deg);
}