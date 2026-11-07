//+------------------------------------------------------------------+
//|                                                SMC_Bridge_EA.mq5 |
//|                                     SMC Quant Auto-Trader Bridge |
//|                             Copyright 2026, Antigravity AI Bot   |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI Bot"
#property link      "https://github.com/thiagooliveira/finance-analysis"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>

input group "=== Configurações da Ponte Python ==="
input string   InpServerURL      = "http://127.0.0.1:8089"; // URL do Servidor Python SMC
input string   InpAuthToken      = "";                      // Token de Autenticação X-Bridge-Token (L-08)
input int      InpPollIntervalMs = 500;                     // Intervalo de Polling (ms)
input int      InpMagicNumber    = 888100;                  // Magic Number Base
input ulong    InpSlippagePoints = 30;                      // Desvio Máximo (Slippage)

CTrade trade;

//+------------------------------------------------------------------+
//| Configura modo de preenchimento suportado pela corretora (L-08)  |
//+------------------------------------------------------------------+
void ConfigureFillingMode(string sym)
{
   uint filling = (uint)SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0)
      trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((filling & SYMBOL_FILLING_IOC) != 0)
      trade.SetTypeFilling(ORDER_FILLING_IOC);
   else
      trade.SetTypeFilling(ORDER_FILLING_RETURN);
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   ConfigureFillingMode(_Symbol);
   
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
//| Retorna cabeçalhos HTTP com autenticação (L-08)                 |
//+------------------------------------------------------------------+
string GetHttpHeaders()
{
   string headers = "Content-Type: application/json\r\n";
   if(StringLen(InpAuthToken) > 0)
   {
      headers += "X-Bridge-Token: " + InpAuthToken + "\r\n";
   }
   return headers;
}

//+------------------------------------------------------------------+
//| Envia dados de conta e cotações para o Python                   |
//+------------------------------------------------------------------+
void SendTelemetry()
{
   string headers = GetHttpHeaders();
   char post[], result[];
   string result_headers;
   
   string payload = StringFormat(
      "{\"type\":\"telemetry\",\"data\":{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"spread\":%.5f,\"point\":%.5f,\"digits\":%d,\"balance\":%.2f,\"equity\":%.2f}}",
      _Symbol,
      SymbolInfoDouble(_Symbol, SYMBOL_BID),
      SymbolInfoDouble(_Symbol, SYMBOL_ASK),
      SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID),
      SymbolInfoDouble(_Symbol, SYMBOL_POINT),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY)
   );
   
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);
   
   ResetLastError();
   WebRequest("POST", InpServerURL, headers, 1000, post, result, result_headers);
}

//+------------------------------------------------------------------+
//| Consulta novas ordens enviadas pelo Python                      |
//+------------------------------------------------------------------+
void PollCommands()
{
   string headers = GetHttpHeaders();
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
//| Executa ordem vinda do motor Python (L-06, L-08)                 |
//+------------------------------------------------------------------+
void ExecuteIncomingCommand(string json_str)
{
   Print("📥 [SMC Bridge EA] Comando recebido: ", json_str);
   
   string action = ExtractJsonValue(json_str, "action");
   string sym = ExtractJsonValue(json_str, "symbol");
   double vol = StringToDouble(ExtractJsonValue(json_str, "volume"));
   double price = StringToDouble(ExtractJsonValue(json_str, "price"));
   double sl = StringToDouble(ExtractJsonValue(json_str, "sl"));
   double tp = StringToDouble(ExtractJsonValue(json_str, "tp"));
   ulong magic = (ulong)StringToInteger(ExtractJsonValue(json_str, "magic"));
   string cmd_id = ExtractJsonValue(json_str, "cmd_id");
   
   if(sym == "") sym = _Symbol;
   ConfigureFillingMode(sym);
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
   else if(action == "BUY_LIMIT")
   {
      // L-06: Ordem limite pendente no nível Fibo OTE
      success = trade.BuyLimit(vol, price, sym, sl, tp, ORDER_TIME_GTC, 0, "SMC-FiboBuyLimit");
      if(success) ticket = trade.ResultOrder();
   }
   else if(action == "SELL_LIMIT")
   {
      // L-06: Ordem limite pendente no nível Fibo OTE
      success = trade.SellLimit(vol, price, sym, sl, tp, ORDER_TIME_GTC, 0, "SMC-FiboSellLimit");
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
   else if(action == "CANCEL")
   {
      ulong ord_ticket = (ulong)StringToInteger(ExtractJsonValue(json_str, "ticket"));
      success = trade.OrderDelete(ord_ticket);
      ticket = ord_ticket;
   }
   
   SendOrderResult(cmd_id, success, ticket, trade.ResultRetcodeDescription(), (int)trade.ResultRetcode());
}

//+------------------------------------------------------------------+
//| Envia confirmação de execução de volta                          |
//+------------------------------------------------------------------+
void SendOrderResult(string cmd_id, bool success, ulong ticket, string comment, int error_code)
{
   string headers = GetHttpHeaders();
   char post[], result[];
   string result_headers;
   
   string payload = StringFormat(
      "{\"type\":\"order_result\",\"cmd_id\":\"%s\",\"result\":{\"success\":%s,\"ticket\":%I64u,\"comment\":\"%s\",\"error_code\":%d}}",
      cmd_id,
      success ? "true" : "false",
      ticket,
      comment,
      error_code
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
