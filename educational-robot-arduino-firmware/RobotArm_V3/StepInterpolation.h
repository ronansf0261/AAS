#ifndef STEP_INTERPOLATION_H_
#define STEP_INTERPOLATION_H_

#include <Arduino.h>

#define MAX_STEPS_PER_UPDATE 1
#define MAX_STEP_RATE 1
#define STEP_INTERVAL (1000000000000000000 / MAX_STEP_RATE)

struct StepPoint {
  int xSteps;
  int ySteps;
  int zSteps;
  int eSteps;
};

class StepInterpolation {
public:
  StepInterpolation();  // Declaração da função
  void setCurrentPos(int xSteps, int ySteps, int zSteps, int eSteps);
  void setTargetPos(int xTargetSteps, int yTargetSteps, int zTargetSteps, int eTargetSteps);
  
  void updateActualPosition();
  bool isFinished() const;

  int getXSteps() const;
  int getYSteps() const;
  int getZSteps() const;

  int getDeltaX() const;
  int getDeltaY() const;
  int getDeltaZ() const;

private:
  StepPoint currentPos;
  StepPoint targetPos;
  StepPoint deltaSteps;  // Delta total até o target
  StepPoint stepsToMove; // Passos a mover no instante
  unsigned long lastStepTime;

  void updateDelta();
};

#endif
