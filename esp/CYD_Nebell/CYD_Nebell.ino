/* =====================================================================
   NEBELL na CYD: monitoramento de sala + animacao da NEBELL
   Placa: ESP32-2432S028R "Cheap Yellow Display" (versao 2 USB)

   Dois modos de tela:
     - MONITORAMENTO (estado espera): relogio, clima, presenca na sala
       e previsao de 3 dias. A animacao fica discreta no canto.
     - ATIVO (ouvindo, pensando, falando, alerta...): a animacao ocupa
       a tela inteira, com o nome do estado embaixo. Ao voltar para
       espera, volta NA HORA para o monitoramento.

   Par do lado do PC: nebell_esp.py (no C:\Nebell-main). Ligue com
   "esp_ligado": true no nebell_config.json. O PC envia {"estado":"..."}
   (ja traduzido para portugues: espera/ouvindo/pensando/falando/alerta);
   este sketch aceita tambem os nomes em ingles, por seguranca.

   Bibliotecas (Gerenciador de Bibliotecas do Arduino):
     - TFT_eSPI, ArduinoJson, WebSockets (Links2004 / Markus Sattler)

   O sensor PIR (HC-SR501) ligado no IO27 e lido aqui na placa.
   O Serial mostra os quadros por segundo (fps) a cada 2 segundos.
   ===================================================================== */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <math.h>

// ======================= COLOQUE SEUS DADOS AQUI =======================
// Nao guarde senha de verdade aqui se for publicar: este arquivo vai para
// um repositorio publico. Preencha na sua copia local e nao commite.
const char* WIFI_NOME   = "SEU_WIFI";        // nome do hotspot (2,4 GHz)
const char* WIFI_SENHA  = "SUA_SENHA";       // senha do hotspot
const char* PC_IP       = "192.168.x.x";     // IP do PC no MESMO wifi ("ipconfig"; NAO o .1)
const uint16_t PC_PORTA = 8765;              // mesma porta do nebell_esp.py (esp_porta)
// =======================================================================

const char* CIDADE    = "Capoeirucu - BA";
const float LATITUDE  = -12.5833;
const float LONGITUDE = -38.9667;
const char* FUSO      = "<-03>3";           // Bahia: UTC-3, sem horario de verao

const int PIR_PIN = 27;                     // sensor de presenca (HC-SR501)
const unsigned long INTERVALO_CLIMA = 15UL * 60UL * 1000UL;
const unsigned long INTERVALO_ERRO  = 60UL * 1000UL;
const unsigned long TEMPO_VOLTA     = 0;    // ms apos espera para voltar ao monitor (0 = na hora)

#define LARGURA 320
#define ALTURA  240
#define MOSTRAR_NOME_ESTADO 1               // 1 = nome do estado embaixo na tela cheia; 0 = sem texto
const int   N_PARTICULAS = 220;
const float TAU = 6.2831853f;

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}
const uint16_t COR_FUNDO   = rgb(6, 9, 20);
const uint16_t COR_BARRA   = rgb(24, 40, 80);
const uint16_t COR_CARTAO  = rgb(22, 32, 62);
const uint16_t COR_FRACO   = rgb(150, 160, 185);
const uint16_t COR_HORA    = rgb(120, 220, 255);
const uint16_t COR_QUENTE  = rgb(255, 150, 70);
const uint16_t COR_FRIO    = rgb(110, 180, 255);
const uint16_t COR_CHUVA   = rgb(80, 160, 255);
const uint16_t COR_SOL     = rgb(255, 205, 40);
const uint16_t COR_VERDE   = rgb(80, 230, 140);
const uint16_t COR_AMBAR   = rgb(255, 180, 50);
const uint16_t COR_ESPERA  = rgb(74, 176, 255);

const char* NOMES_DIA[] = { "Domingo", "Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado" };
const char* SIGLAS_DIA[] = { "Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab" };

TFT_eSPI tft = TFT_eSPI();
WebSocketsClient ws;

// ---------------- Previsao do tempo ----------------
struct Clima {
  bool  valido = false;
  float temperatura, sensacao, vento;
  int   umidade, codigo;
  bool  dia;
  char  atualizado[6] = "--:--";
  int   diaSemana[3], diaCodigo[3], diaChuva[3];
  float diaMax[3], diaMin[3];
};
Clima clima;

// ---------------- Presenca ----------------
bool presente = false;
char ultimoMovimento[6] = "--:--";

// ---------------- Animacao ----------------
enum Forma { F_ORBITA, F_ONDA, F_ELIPSE, F_ESFERA, F_CAOS, F_ESPIRAL };

struct Particula { float x, y; int px, py; };
Particula ps[N_PARTICULAS];

Forma    forma = F_ORBITA;
uint16_t cor   = COR_ESPERA;
char     estadoAtual[24] = "espera";
float    fase = 0;

bool          modoAtivo     = false;   // true = tela cheia com a animacao
bool          voltaPendente = false;   // estado voltou para espera, aguardando
unsigned long momentoEspera = 0;

// Timers
unsigned long ultimoQuadro = 0, ultimoRelogio = 0, ultimoPir = 0, ultimoCabecalho = 0;
unsigned long ultimaBusca = 0, ultimoRelatorio = 0, quadrosNoPeriodo = 0;
bool ultimaBuscaDeuCerto = false;

// =====================================================================
//  Funcoes de ajuda
// =====================================================================

const char* descricaoTempo(int codigo) {
  switch (codigo) {
    case 0:  return "Ceu limpo";
    case 1:  return "Poucas nuvens";
    case 2:  return "Parc. nublado";
    case 3:  return "Nublado";
    case 45: case 48: return "Neblina";
    case 51: case 53: case 55: case 56: case 57: return "Garoa";
    case 61: return "Chuva fraca";
    case 63: return "Chuva";
    case 65: return "Chuva forte";
    case 80: case 81: return "Pancadas";
    case 82: return "Temporal";
    case 95: return "Trovoada";
    case 96: case 97: case 99: return "Trovoada forte";
    default: return "---";
  }
}

int diaDaSemana(const char* data) {
  if (data == nullptr) return 0;
  int a = atoi(data), m = atoi(data + 5), d = atoi(data + 8);
  static const int t[] = { 0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4 };
  if (m < 3) a -= 1;
  return (a + a / 4 - a / 100 + a / 400 + t[(m - 1) % 12] + d) % 7;
}

void desenharSol(int cx, int cy, int r) {
  tft.fillCircle(cx, cy, r, COR_SOL);
}

// =====================================================================
//  Partes da tela de monitoramento
// =====================================================================

void desenharCabecalho() {
  tft.fillRect(0, 0, LARGURA, 24, COR_BARRA);
  tft.setTextDatum(ML_DATUM);
  tft.setTextColor(TFT_WHITE, COR_BARRA);
  tft.drawString(CIDADE, 8, 12, 2);

  if (clima.valido) {
    tft.setTextDatum(MR_DATUM);
    tft.setTextColor(COR_FRACO, COR_BARRA);
    tft.drawString(String("atualizado ") + clima.atualizado, 288, 12, 1);
  }

  int barras = 0;
  if (WiFi.status() == WL_CONNECTED) {
    int rssi = WiFi.RSSI();
    barras = rssi > -55 ? 4 : rssi > -65 ? 3 : rssi > -75 ? 2 : rssi > -85 ? 1 : 0;
  }
  for (int i = 0; i < 4; i++) {
    int h = 4 + i * 3;
    tft.fillRect(295 + i * 5, 18 - h, 3, h, i < barras ? TFT_WHITE : COR_CARTAO);
  }
}

// Relogio e data: so redesenha a propria area
void desenharRelogio(const struct tm& agora) {
  tft.fillRect(4, 28, 162, 64, COR_FUNDO);
  char hora[12];
  snprintf(hora, sizeof(hora), "%02d:%02d:%02d", agora.tm_hour, agora.tm_min, agora.tm_sec);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COR_HORA, COR_FUNDO);
  tft.drawString(hora, 8, 36, 4);

  char data[24];
  snprintf(data, sizeof(data), "%s %02d/%02d/%04d", SIGLAS_DIA[agora.tm_wday],
           agora.tm_mday, agora.tm_mon + 1, agora.tm_year + 1900);
  tft.setTextColor(COR_FRACO, COR_FUNDO);
  tft.drawString(data, 8, 72, 2);
}

// Cartao RUA: clima atual
void desenharRua() {
  tft.fillRoundRect(170, 32, 142, 76, 8, COR_CARTAO);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COR_FRACO, COR_CARTAO);
  tft.drawString("RUA", 180, 40, 2);

  if (!clima.valido) {
    tft.drawString("Buscando...", 180, 70, 2);
    return;
  }
  desenharSol(196, 72, 9);
  tft.setTextColor(TFT_WHITE, COR_CARTAO);
  tft.drawString(String(lroundf(clima.temperatura)) + "C", 214, 58, 4);
  tft.setTextColor(COR_FRACO, COR_CARTAO);
  tft.drawString(descricaoTempo(clima.codigo), 180, 90, 2);

  tft.setTextDatum(TR_DATUM);
  tft.drawString("umid " + String(clima.umidade) + "%", 302, 40, 1);
}

// Cartao QUARTO / SALA: presenca detectada pelo PIR
void desenharPresenca() {
  tft.fillRoundRect(8, 116, 304, 50, 8, COR_CARTAO);
  if (presente) tft.drawRoundRect(8, 116, 304, 50, 8, COR_AMBAR);

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(COR_FRACO, COR_CARTAO);
  tft.drawString("QUARTO / SALA", 18, 124, 2);

  uint16_t c = presente ? COR_AMBAR : COR_VERDE;
  tft.fillCircle(20, 150, 4, c);
  tft.setTextColor(c, COR_CARTAO);
  tft.drawString(presente ? "Alguem detectado" : "Ninguem detectado", 30, 141, 2);

  tft.setTextDatum(TR_DATUM);
  tft.setTextColor(COR_FRACO, COR_CARTAO);
  tft.drawString(String("mov. ") + ultimoMovimento, 304, 124, 2);
}

// Tres cartoes de previsao
void desenharPrevisao() {
  for (int k = 0; k < 3; k++) {
    int X = 8 + k * 82, Y = 174;
    tft.fillRoundRect(X, Y, 78, 56, 8, COR_CARTAO);
    if (!clima.valido) continue;

    tft.setTextDatum(TL_DATUM);
    tft.setTextColor(TFT_WHITE, COR_CARTAO);
    tft.drawString(k == 0 ? "Hoje" : SIGLAS_DIA[clima.diaSemana[k]], X + 6, Y + 6, 2);

    tft.setTextColor(COR_QUENTE, COR_CARTAO);
    tft.drawString(String(lroundf(clima.diaMax[k])) + "C", X + 6, Y + 26, 2);
    tft.setTextColor(COR_FRIO, COR_CARTAO);
    tft.drawString(String(lroundf(clima.diaMin[k])) + "C", X + 40, Y + 26, 2);

    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(COR_CHUVA, COR_CARTAO);
    tft.drawString(String(clima.diaChuva[k]) + "%", X + 72, Y + 42, 1);
  }
}

void desenharTelaMonitoramento() {
  tft.fillScreen(COR_FUNDO);
  desenharCabecalho();
  struct tm agora;
  if (getLocalTime(&agora, 50)) desenharRelogio(agora);
  desenharRua();
  desenharPresenca();
  desenharPrevisao();
}

// =====================================================================
//  Animacao
// =====================================================================

void aplicarEstado(const char* e) {
  strncpy(estadoAtual, e, sizeof(estadoAtual) - 1);
  estadoAtual[sizeof(estadoAtual) - 1] = 0;

  if      (!strcmp(e, "ouvindo")  || !strcmp(e, "listening")) { forma = F_ONDA;    cor = rgb( 80,230,140); }
  else if (!strcmp(e, "pensando") || !strcmp(e, "thinking"))  { forma = F_ELIPSE;  cor = rgb(255, 77,122); }
  else if (!strcmp(e, "falando")  || !strcmp(e, "speaking"))  { forma = F_ESFERA;  cor = rgb(120,220,255); }
  else if (!strcmp(e, "alerta")   || !strcmp(e, "erro"))      { forma = F_CAOS;    cor = rgb(255, 48, 92); }
  else                                                        { forma = F_ESPIRAL; cor = rgb( 74,134,255); }
}

#if MOSTRAR_NOME_ESTADO
// Nome do estado embaixo da animacao em tela cheia. So redesenha quando
// o estado muda; as particulas ficam acima de y=214, entao nao o apagam.
void desenharNomeEstado() {
  const char* nome;
  switch (forma) {
    case F_ONDA:   nome = "OUVINDO";  break;
    case F_ELIPSE: nome = "PENSANDO"; break;
    case F_ESFERA: nome = "FALANDO";  break;
    case F_CAOS:   nome = "ALERTA";   break;
    default:       nome = "";         break;
  }
  tft.fillRect(0, 214, LARGURA, 26, COR_FUNDO);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(cor, COR_FUNDO);
  tft.drawString(nome, LARGURA / 2, 226, 2);
}
#endif

// Posicao-alvo da particula i. (cx, cy) = centro, esc = escala, f = forma
void alvo(int i, float &tx, float &ty, float cx, float cy, float esc, int f) {
  float a = i * TAU / N_PARTICULAS, r;
  switch (f) {
    case F_ORBITA: {
      float raio = (i % 2 == 0) ? 50 : 70;
      float d = (i % 2 == 0) ? 1 : -1;
      a += d * fase * 0.4f;
      r = raio * esc;
      break;
    }
    case F_ONDA:
      a = i * TAU * 7 / N_PARTICULAS;
      r = (20 + 60 * fmodf((float)i / N_PARTICULAS + fase * 0.12f, 1.0f)) * esc;
      break;
    case F_ELIPSE: {
      a += fase * 1.5f;
      float x = cosf(a) * 78 * esc, y = sinf(a) * 34 * esc;
      float c = cosf(fase * 0.5f), s = sinf(fase * 0.5f);
      tx = cx + x * c - y * s;
      ty = cy + x * s + y * c;
      return;
    }
    case F_ESFERA: {
      float phi = acosf(1 - 2 * (i + 0.5f) / N_PARTICULAS);
      float th  = M_PI * (1 + sqrtf(5)) * i;
      float R   = (48 + 12 * sinf(fase * 4)) * esc;
      float x = sinf(phi) * cosf(th), y = cosf(phi), z = sinf(phi) * sinf(th);
      float xr = x * cosf(fase) + z * sinf(fase);
      tx = cx + xr * R;
      ty = cy + y * R;
      return;
    }
    case F_CAOS:
      a = random(0, 628) / 100.0f;
      r = (50 + random(-25, 25)) * esc;
      break;
    case F_ESPIRAL:
    default:
      a = i * 0.35f + fase * 2;
      r = (12 + 60 * ((float)i / N_PARTICULAS)) * esc;
      break;
  }
  tx = cx + cosf(a) * r;
  ty = cy + sinf(a) * r;
}

// Desenha as particulas apagando cada uma na posicao antiga
void animarParticulas(float cx, float cy, float esc, int f, uint16_t corP, int tamanho) {
  for (int i = 0; i < N_PARTICULAS; i++) {
    tft.fillRect(ps[i].px, ps[i].py, tamanho, tamanho, COR_FUNDO);
    float tx, ty;
    alvo(i, tx, ty, cx, cy, esc, f);
    ps[i].x += (tx - ps[i].x) * 0.12f;
    ps[i].y += (ty - ps[i].y) * 0.12f;
    ps[i].px = (int)ps[i].x;
    ps[i].py = (int)ps[i].y;
    tft.fillRect(ps[i].px, ps[i].py, tamanho, tamanho, corP);
  }
  fase += 0.05f;
}

// Joga todas as particulas para perto de um ponto (usado ao trocar de modo)
void resetarParticulas(float cx, float cy, float espalho) {
  for (int i = 0; i < N_PARTICULAS; i++) {
    ps[i].x = cx + random(-espalho, espalho);
    ps[i].y = cy + random(-espalho, espalho);
    ps[i].px = (int)ps[i].x;
    ps[i].py = (int)ps[i].y;
  }
}

// =====================================================================
//  Internet: previsao
// =====================================================================

bool buscarClima() {
  if (WiFi.status() != WL_CONNECTED) return false;

  String url = "https://api.open-meteo.com/v1/forecast"
               "?latitude=" + String(LATITUDE, 4) +
               "&longitude=" + String(LONGITUDE, 4) +
               "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
               "is_day,weather_code,wind_speed_10m"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
               "precipitation_probability_max"
               "&timezone=America%2FBahia&forecast_days=3";

  WiFiClientSecure cliente;
  cliente.setInsecure();
  HTTPClient http;
  http.begin(cliente, url);
  int status = http.GET();
  if (status != 200) {
    Serial.printf("Erro ao buscar a previsao: %d\n", status);
    http.end();
    return false;
  }
  String resposta = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, resposta)) return false;

  JsonObject atual = doc["current"];
  clima.temperatura = atual["temperature_2m"] | 0.0f;
  clima.sensacao    = atual["apparent_temperature"] | 0.0f;
  clima.umidade     = atual["relative_humidity_2m"] | 0;
  clima.vento       = atual["wind_speed_10m"] | 0.0f;
  clima.codigo      = atual["weather_code"] | 0;
  clima.dia         = (atual["is_day"] | 1) == 1;

  JsonObject diario = doc["daily"];
  for (int i = 0; i < 3; i++) {
    clima.diaSemana[i] = diaDaSemana(diario["time"][i].as<const char*>());
    clima.diaCodigo[i] = diario["weather_code"][i] | 0;
    clima.diaMax[i]    = diario["temperature_2m_max"][i] | 0.0f;
    clima.diaMin[i]    = diario["temperature_2m_min"][i] | 0.0f;
    clima.diaChuva[i]  = diario["precipitation_probability_max"][i] | 0;
  }

  struct tm agora;
  if (getLocalTime(&agora, 100)) strftime(clima.atualizado, sizeof(clima.atualizado), "%H:%M", &agora);
  clima.valido = true;
  return true;
}

void atualizarClima() {
  ultimaBuscaDeuCerto = buscarClima();
  ultimaBusca = millis();
  desenharCabecalho();
  desenharRua();
  desenharPrevisao();
}

// =====================================================================
//  WebSocket: recebe o estado do PC
// =====================================================================

void aoReceberWs(WStype_t tipo, uint8_t* payload, size_t tamanho) {
  switch (tipo) {
    case WStype_CONNECTED:
      Serial.println("WebSocket conectado ao PC");
      break;
    case WStype_DISCONNECTED:
      Serial.println("WebSocket caiu. Tentando de novo...");
      break;
    case WStype_TEXT: {
      JsonDocument doc;
      if (deserializeJson(doc, (const char*)payload, tamanho)) return;
      const char* e = doc["estado"] | "espera";
      Serial.printf("Estado: %s\n", e);

      if (!strcmp(e, "espera") || !strcmp(e, "idle") || !strcmp(e, "encerrando")) {
        // Volta ao monitoramento (na hora, por TEMPO_VOLTA = 0)
        if (modoAtivo && !voltaPendente) {
          voltaPendente = true;
          momentoEspera = millis();
        }
      } else {
        // Estado ativo: cancela a volta e entra na tela cheia
        voltaPendente = false;
        aplicarEstado(e);
        if (!modoAtivo) {
          modoAtivo = true;
          tft.fillScreen(COR_FUNDO);
          resetarParticulas(160, 120, 60);
        }
#if MOSTRAR_NOME_ESTADO
        desenharNomeEstado();
#endif
      }
      break;
    }
    default:
      break;
  }
}

// =====================================================================

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);

  tft.init();
  tft.setRotation(1);
  tft.writecommand(0x26); tft.writedata(2);
  delay(120);
  tft.writecommand(0x26); tft.writedata(1);
  tft.fillScreen(COR_FUNDO);

  resetarParticulas(285, 204, 8);

  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(TFT_WHITE, COR_FUNDO);
  tft.drawString("Conectando ao WiFi...", 160, 120, 2);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_NOME, WIFI_SENHA);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.print("\nWiFi OK. IP da placa: ");
  Serial.println(WiFi.localIP());

  configTzTime(FUSO, "a.st1.ntp.br", "pool.ntp.org");
  struct tm agora;
  while (!getLocalTime(&agora, 2000)) Serial.println("Esperando a hora...");

  atualizarClima();
  desenharTelaMonitoramento();

  ws.begin(PC_IP, PC_PORTA, "/");
  ws.onEvent(aoReceberWs);
  ws.setReconnectInterval(3000);
}

void loop() {
  ws.loop();
  unsigned long agoraMs = millis();

  // 1) Volta ao monitoramento depois que o estado virou espera
  //    (TEMPO_VOLTA = 0 -> na hora, ja no proximo laco)
  if (voltaPendente && agoraMs - momentoEspera >= TEMPO_VOLTA) {
    voltaPendente = false;
    modoAtivo = false;
    resetarParticulas(285, 204, 8);
    desenharTelaMonitoramento();
  }

  // 2) Animacao: tela cheia no modo ativo, canto no monitoramento
  if (agoraMs - ultimoQuadro >= 33) {
    ultimoQuadro = agoraMs;
    if (modoAtivo) animarParticulas(160, 120, 1.0f, forma, cor, 2);
    else           animarParticulas(285, 204, 0.25f, F_ORBITA, COR_ESPERA, 1);
    quadrosNoPeriodo++;
  }

  // Os itens abaixo so mexem na tela de monitoramento
  if (!modoAtivo) {
    // 3) Relogio a cada segundo
    if (agoraMs - ultimoRelogio >= 1000) {
      ultimoRelogio = agoraMs;
      struct tm agora;
      if (getLocalTime(&agora, 10)) desenharRelogio(agora);
    }

    // 4) Presenca a cada 200 ms (so redesenha quando muda)
    if (agoraMs - ultimoPir >= 200) {
      ultimoPir = agoraMs;
      bool agoraPresente = digitalRead(PIR_PIN) == HIGH;
      if (agoraPresente != presente) {
        presente = agoraPresente;
        if (presente) {
          struct tm agora;
          if (getLocalTime(&agora, 10)) strftime(ultimoMovimento, sizeof(ultimoMovimento), "%H:%M", &agora);
        }
        desenharPresenca();
      }
    }

    // 5) Cabecalho (sinal do WiFi) a cada 10 s
    if (agoraMs - ultimoCabecalho >= 10000) {
      ultimoCabecalho = agoraMs;
      desenharCabecalho();
    }

    // 6) Previsao: a cada 15 min (ou 1 min se a ultima deu erro)
    unsigned long espera = ultimaBuscaDeuCerto ? INTERVALO_CLIMA : INTERVALO_ERRO;
    if (agoraMs - ultimaBusca > espera) atualizarClima();
  }

  // Relatorio de quadros por segundo a cada 2 segundos
  if (agoraMs - ultimoRelatorio >= 2000) {
    Serial.printf("fps: %.1f\n", quadrosNoPeriodo / 2.0f);
    quadrosNoPeriodo = 0;
    ultimoRelatorio = agoraMs;
  }
}
