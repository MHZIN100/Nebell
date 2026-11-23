# NEBELL na placa ESP32 (CYD) — monitor remoto

A placa **ESP32-2432S028R ("Cheap Yellow Display", 320×240)** mostra, de
longe, o que a NEBELL está fazendo no PC: ela recebe o estado por WebSocket
e anima a tela conforme (espera, ouvindo, pensando, falando, alerta), além
de um monitoramento de sala (relógio, clima e presença) quando está parada.

## Como as duas pontas conversam

- **PC:** `nebell_esp.py` (na raiz do projeto) é um servidor WebSocket na
  porta `8765`. A cada mudança de estado, o `ui_state` da NEBELL manda
  `{"estado": "..."}` para a placa — já traduzido para português
  (`idle→espera`, `listening→ouvindo`, `thinking→pensando`,
  `speaking→falando`, `erro→alerta`). Funciona mesmo com a janela fechada.
- **Placa:** `CYD_Nebell/CYD_Nebell.ino` conecta no PC como cliente
  WebSocket e anima conforme o estado recebido.

## Ligar o lado do PC

No `nebell_config.json` (ao lado do `nebell.py`):

```json
{ "esp_ligado": true, "esp_porta": 8765 }
```

Reinicie a NEBELL. A porta `8765` precisa estar liberada no firewall do
Windows (você já criou a regra).

## Flashar a placa

1. **Bibliotecas** (Gerenciador de Bibliotecas do Arduino): `TFT_eSPI`,
   `ArduinoJson`, `WebSockets` (de Markus Sattler / Links2004).
2. Copie a pasta `CYD_Nebell/` para a sua pasta de sketches do Arduino.
3. Abra `CYD_Nebell.ino` e preencha, no topo, **seus dados**:
   - `WIFI_NOME` e `WIFI_SENHA`: o hotspot (2,4 GHz) onde o **PC também**
     está. (Não commite suas senhas — este repositório é público.)
   - `PC_IP`: o IP do PC nesse wifi (veja com `ipconfig`; é o endereço do
     PC, **não** o `.1` do roteador).
4. Compile e grave na placa.

## Conferir a conexão

- No Monitor Serial (115200), a placa imprime `WebSocket conectado ao PC`
  e os estados que chegam. Também mostra os `fps` a cada 2 s.
- Fale/use a NEBELL no PC: a tela da placa deve entrar em tela cheia com a
  animação do estado e **voltar na hora** ao monitoramento quando parar.

## Ajustes rápidos (no topo do .ino)

- `MOSTRAR_NOME_ESTADO` — `1` mostra o nome do estado embaixo; `0` esconde.
- `TEMPO_VOLTA` — `0` volta na hora ao monitoramento; aumente (ms) para
  segurar a animação um pouco mais.
- `PIR_PIN` — pino do sensor de presença (HC-SR501) no IO27.
