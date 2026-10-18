//+------------------------------------------------------------------+
//|                                                SMC_Bridge_EA.mq5 |
//|                                     SMC Quant Auto-Trader Bridge |
//|                             Copyright 2026, Antigravity AI Bot   |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI Bot"
#property link      "https://github.com/thiagooliveira/finance-analysis"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

input group "=== Configurações da Ponte Python ==="
input string   InpServerURL   = "http://127.0.0.1:8089"; // URL do Servidor Python SMC
input int      InpPollIntervalMs = 500;                  // Intervalo de Polling (ms)
input int      InpMagicNumber    = 888100;               // Magic Number Base
input ulong    InpSlippagePoints = 30;                   // Desvio Máximo (Slippage)

CTrade trade;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFilling(ORDER_FILLING_FOK);
   
   EventSetMillisecondTimer(InpPollIntervalMs);
   Print("🚀 [SMC Bridge EA] Inicializado com sucesso! Conectando a ", InpServerURL);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("🛑 [SMC Bridge EA] Finalizado. Razão: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event function (Polling contínuo)                          |
//+------------------------------------------------------------------+
void OnTimer()
{
   SendTelemetry();
   PollCommands();
}

//+------------------------------------------------------------------+
//| Envia dados de conta e cotações para o Python                   |
//+------------------------------------------------------------------+
void SendTelemetry()
{
   string headers = "Content-Type: application/json\r\n";
   char post[], result[];
   string result_headers;
   
   string payload = StringFormat(
      "{\"type\":\"telemetry\",\"data\":{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"balance\":%.2f,\"equity\":%.2f}}",
      _Symbol,
      SymbolInfoDouble(_Symbol, SYMBOL_BID),
      SymbolInfoDouble(_Symbol, SYMBOL_ASK),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY)
   );
   
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);
   
   ResetLastError();
   int res = WebRequest("POST", InpServerURL, headers, 1000, post, result, result_headers);
}

//+------------------------------------------------------------------+
//| Consulta novas ordens enviadas pelo Python                      |
//+------------------------------------------------------------------+
void PollCommands()
{
   string headers = "Content-Type: application/json\r\n";
   char post[], result[];
   string result_headers;
   
   ResetLastError();
   int res = WebRequest("GET", InpServerURL, headers, 1000, post, result, result_headers);
   if(res == 200 && ArraySize(result) > 0)
   {
      string resp = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
      if(StringFind(resp, "\"status\":\"command\"") >= 0 || StringFind(resp, "\"status\": \"command\"") >= 0)
      {
         ExecuteIncomingCommand(resp);
      }
   }
}

//+------------------------------------------------------------------+
//| Executa ordem vinda do motor Python                             |
//+------------------------------------------------------------------+
void ExecuteIncomingCommand(string json_str)
{
   Print("📥 [SMC Bridge EA] Comando recebido: ", json_str);
   // Exemplo de payload esperado:
   // {"action":"BUY","symbol":"XAUUSD","volume":0.02,"sl":2640.50,"tp":2670.00,"magic":888101,"cmd_id":"c123"}
   
   string action = ExtractJsonValue(json_str, "action");
   string sym = ExtractJsonValue(json_str, "symbol");
   double vol = StringToDouble(ExtractJsonValue(json_str, "volume"));
   double sl = StringToDouble(ExtractJsonValue(json_str, "sl"));
   double tp = StringToDouble(ExtractJsonValue(json_str, "tp"));
   ulong magic = (ulong)StringToInteger(ExtractJsonValue(json_str, "magic"));
   string cmd_id = ExtractJsonValue(json_str, "cmd_id");
   
   if(sym == "") sym = _Symbol;
   trade.SetExpertMagicNumber(magic > 0 ? magic : InpMagicNumber);
   
   bool success = false;
   ulong ticket = 0;
   
   if(action == "BUY")
   {
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      success = trade.Buy(vol, sym, ask, sl, tp, "SMC-AutoBuy");
      if(success) ticket = trade.ResultOrder();
   }
   else if(action == "SELL")
   {
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      success = trade.Sell(vol, sym, bid, sl, tp, "SMC-AutoSell");
      if(success) ticket = trade.ResultOrder();
   }
   else if(action == "MODIFY")
   {
      ulong pos_ticket = (ulong)StringToInteger(ExtractJsonValue(json_str, "ticket"));
      success = trade.PositionModify(pos_ticket, sl, tp);
      ticket = pos_ticket;
   }
   else if(action == "CLOSE")
   {
      ulong pos_ticket = (ulong)StringToInteger(ExtractJsonValue(json_str, "ticket"));
      success = trade.PositionClose(pos_ticket);
      ticket = pos_ticket;
   }
   
   // Envia resultado de volta para o Python
   SendOrderResult(cmd_id, success, ticket, trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Envia confirmação de execução de volta                          |
//+------------------------------------------------------------------+
void SendOrderResult(string cmd_id, bool success, ulong ticket, string comment)
{
   string headers = "Content-Type: application/json\r\n";
   char post[], result[];
   string result_headers;
   
   string payload = StringFormat(
      "{\"type\":\"order_result\",\"cmd_id\":\"%s\",\"result\":{\"success\":%s,\"ticket\":%I64u,\"comment\":\"%s\"}}",
      cmd_id,
      success ? "true" : "false",
      ticket,
      comment
   );
   
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);
   WebRequest("POST", InpServerURL, headers, 1000, post, result, result_headers);
}

//+------------------------------------------------------------------+
//| Utilitário simples para extrair valor de chave JSON             |
//+------------------------------------------------------------------+
string ExtractJsonValue(string json, string key)
{
   string pattern = "\"" + key + "\":";
   int pos = StringFind(json, pattern);
   if(pos < 0)
   {
      pattern = "\"" + key + "\" :";
      pos = StringFind(json, pattern);
   }
   if(pos < 0) return "";
   
   pos += StringLen(pattern);
   while(pos < StringLen(json) && (StringSubstr(json, pos, 1) == " " || StringSubstr(json, pos, 1) == "\"")) pos++;
   
   int end = pos;
   while(end < StringLen(json) && StringSubstr(json, end, 1) != "\"" && StringSubstr(json, end, 1) != "," && StringSubstr(json, end, 1) != "}") end++;
   
   return StringSubstr(json, pos, end - pos);
}
//+------------------------------------------------------------------+
