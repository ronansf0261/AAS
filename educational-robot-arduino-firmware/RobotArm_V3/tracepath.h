#ifndef TRACEPATH_H_
#define TRACEPATH_H_

class Tracepath {
public:
  //void resetInterpolation(float px, float py, float pz);
  //void resetInterpolation(float p1x, float p1y, float p1z, float p2x, float p2y, float p2z);
  //void resetInterpolation(Point p0, Point p1);
  Tracepath();  
  //void setTrace(float trace_interval, float p1x, float p1y, float p1z, float p2x, float p2y, float p2z);  
  //void traceRoute(float p1x, float p1y, float p1z);
  void updateActualTracePosition(float axmm, float aymm, float azmm); //atualiza a posicao presente
  void updateEndTracePosition(float axmm, float aymm, float azmm); //atualiza a posicao ao final do comando
  void setInterval(float trace_interval); //seta o intervalo de Log de posicao
  float getInterval(); //informa o intervalo de LOG de posicao
  void enableTrace(float interval = 5.0); //por default esta habilitado no construtor da classe
  void disableTrace();
  void enableLogData(); //habilita ou desabilita envio de logs de posiçao
  void disableLogData();
  
    
private:
  
  float xLastPosmm = 0; //Ultima posição antes de atualizacao de reatreio (só é atualizada qdo completa o intervalo)
  float yLastPosmm = 0;
  float zLastPosmm = 0;
  float xActualPosmm; //Posicao atual (em trmpo real)
  float yActualPosmm;
  float zActualPosmm;
  //float xDeltaPos;
  //float yDeltaPos;
  //float zDeltaPos;
  float gapPath; //indica intervalo de atualização de dados de traçado (em milimetros)
  //float dActualTrace; //calcula o espeço percorrido entre a posicao atual e a última para comparar com o gap
  bool enablePath; //se true, habilita o trace
  bool enableLog; //para habilitar ou desabilitar o envio dos dados de posicionamento.
};

#endif
