#include "tracepath.h"
#include "logger.h"


#include <Arduino.h>


Tracepath::Tracepath(){
  enablePath = true;
  enableLog = false;
  gapPath = 5.0; //inicializa com 5,0 mm de gap
}

void Tracepath::updateActualTracePosition(float axmm, float aymm, float azmm){
  
  if(!enablePath){
    return;
    }
  float a1;
  float b1;
  float c1;
  xActualPosmm = axmm;
  yActualPosmm = aymm;
  zActualPosmm = azmm;

  a1 = xActualPosmm - xLastPosmm;
  b1 = yActualPosmm - yLastPosmm;
  c1 = zActualPosmm - zLastPosmm;
  float dist1 = sqrt(a1*a1 + b1*b1 + c1*c1);

  if(dist1 >= gapPath){
      xLastPosmm = xActualPosmm;
      yLastPosmm = yActualPosmm;
      zLastPosmm = zActualPosmm;
      if(enableLog){
        Logger::logTRACE("CURRENT POSITION: [X:"+String(xLastPosmm)+" Y:"+String(yLastPosmm)+" Z:"+String(zLastPosmm)+"]");
        
      }
    }        
   
  }

  void Tracepath::updateEndTracePosition(float axmm, float aymm, float azmm){
  
  if(!enablePath){
    return;
    }  
  if((axmm == xLastPosmm) && (aymm == yLastPosmm) && (azmm == zLastPosmm)) return; //não precisa atualizar

  xActualPosmm = axmm;
  yActualPosmm = aymm;
  zActualPosmm = azmm;
  xLastPosmm = axmm;
  yLastPosmm = aymm;
  zLastPosmm = azmm;
  if(enableLog){
        Logger::logTRACE("CURRENT POSITION: [X:"+String(xLastPosmm)+" Y:"+String(yLastPosmm)+" Z:"+String(zLastPosmm)+"]");
        
      }
       
  }

  void Tracepath::setInterval(float trace_interval){
  gapPath = trace_interval;
  } //seta o intervalo de Log de posicao

  float Tracepath::getInterval(){
  return gapPath;
  } //informa o intervalo de LOG de posicao

  void Tracepath::enableTrace(float interval){
  gapPath = interval;
  enablePath =true;

  } //por default esta habilitado no construtor da classe
  void Tracepath::disableTrace(){
   enablePath =false;
  }

  void Tracepath::enableLogData(){
    enableLog = true;
  }

   void Tracepath::disableLogData(){
    enableLog = false;
  }