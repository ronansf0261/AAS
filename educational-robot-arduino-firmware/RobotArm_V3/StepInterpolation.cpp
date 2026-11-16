#include "StepInterpolation.h"

StepInterpolation::StepInterpolation() {
  currentPos = {0, 0, 0, 0};
  targetPos = {0, 0, 0, 0};
  deltaSteps = {0, 0, 0, 0};
  stepsToMove = {0, 0, 0, 0};
  lastStepTime = 0;
}

void StepInterpolation::setCurrentPos(int xSteps, int ySteps, int zSteps, int eSteps) {
  currentPos.xSteps = xSteps;
  currentPos.ySteps = ySteps;
  currentPos.zSteps = zSteps;
  currentPos.eSteps = eSteps;
  
  updateDelta();  // Atualiza o delta sempre que a posição atual for configurada
}

void StepInterpolation::setTargetPos(int xTargetSteps, int yTargetSteps, int zTargetSteps, int eTargetSteps) {
  targetPos.xSteps = xTargetSteps;
  targetPos.ySteps = yTargetSteps;
  targetPos.zSteps = zTargetSteps;
  targetPos.eSteps = eTargetSteps;

  updateDelta();
}

void StepInterpolation::updateDelta() {
  // Calcula o delta entre a posição atual e o alvo
  deltaSteps.xSteps = targetPos.xSteps - currentPos.xSteps;
  deltaSteps.ySteps = targetPos.ySteps - currentPos.ySteps;
  deltaSteps.zSteps = targetPos.zSteps - currentPos.zSteps;
  deltaSteps.eSteps = targetPos.eSteps - currentPos.eSteps;

  // Limita o delta a no máximo 1 passo por eixo, respeitando a direção
  stepsToMove.xSteps = (deltaSteps.xSteps != 0) ? (deltaSteps.xSteps > 0 ? 1 : -1) : 0;
  stepsToMove.ySteps = (deltaSteps.ySteps != 0) ? (deltaSteps.ySteps > 0 ? 1 : -1) : 0;
  stepsToMove.zSteps = (deltaSteps.zSteps != 0) ? (deltaSteps.zSteps > 0 ? 1 : -1) : 0;
  stepsToMove.eSteps = (deltaSteps.eSteps != 0) ? (deltaSteps.eSteps > 0 ? 1 : -1) : 0;
}


void StepInterpolation::updateActualPosition() {
  unsigned long currentTime = micros();
  
  if (currentTime - lastStepTime >= STEP_INTERVAL) {

    lastStepTime = currentTime;
    updateDelta();  // Recalcula o delta para o próximo ciclo

    // Se atingir o alvo, garantir que os deltas sejam zerados
    if (isFinished()) {
      deltaSteps = {0, 0, 0, 0};
      stepsToMove = {0, 0, 0, 0};
    }
  }
}

bool StepInterpolation::isFinished() const {
  return (currentPos.xSteps == targetPos.xSteps &&
          currentPos.ySteps == targetPos.ySteps &&
          currentPos.zSteps == targetPos.zSteps &&
          currentPos.eSteps == targetPos.eSteps);
}

int StepInterpolation::getXSteps() const {
  return stepsToMove.xSteps;  // Retorna o delta de passos calculado para este ciclo
}

int StepInterpolation::getYSteps() const {
  return stepsToMove.ySteps;
}

int StepInterpolation::getZSteps() const {
  return stepsToMove.zSteps;
}

int StepInterpolation::getDeltaX() const {
  return deltaSteps.xSteps;
}

int StepInterpolation::getDeltaY() const {
  return deltaSteps.ySteps;
}

int StepInterpolation::getDeltaZ() const {
  return deltaSteps.zSteps;
}
