//+------------------------------------------------------------------+
//| Export_History.mq5                                               |
//| Exporta histórico OHLC + spread de vários ativos para CSV.       |
//|                                                                  |
//| Como usar:                                                       |
//|  1. Copie para <Pasta de dados>/MQL5/Scripts/ e compile (F7).     |
//|  2. Arraste o script para qualquer gráfico.                       |
//|  3. Ajuste a lista de ativos (nomes exatos da sua corretora).     |
//|  4. Os arquivos saem em <Pasta de dados>/MQL5/Files/smc_export/   |
//|     (Arquivo > Abrir pasta de dados).                             |
//|                                                                  |
//| Horário: o MT5 grava no fuso do SERVIDOR da corretora.            |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpSymbols   = "XAUUSD,NAS100,US30,US500,GER40,BRENT,EURUSD,GBPUSD,USDJPY,AUDUSD";
input bool   InpD1        = true;
input bool   InpH4        = true;
input bool   InpH1        = true;
input int    InpMaxBars   = 100000;
input string InpFolder    = "smc_export";

string TfName(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_D1: return "D1";
      case PERIOD_H4: return "H4";
      case PERIOD_H1: return "H1";
   }
   return EnumToString(tf);
}

bool ExportOne(string sym, ENUM_TIMEFRAMES tf)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   // força o terminal a carregar o histórico do servidor
   datetime first_date = 0;
   SeriesInfoInteger(sym, tf, SERIES_SERVER_FIRSTDATE, first_date);
   int copied = CopyRates(sym, tf, 0, InpMaxBars, rates);
   if(copied <= 0)
   {
      PrintFormat("Falha ao copiar %s %s (erro %d)", sym, TfName(tf), GetLastError());
      return false;
   }
   string fname = InpFolder + "\\" + sym + "_" + TfName(tf) + ".csv";
   int h = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
   {
      PrintFormat("Falha ao abrir %s (erro %d)", fname, GetLastError());
      return false;
   }
   FileWrite(h, "time", "open", "high", "low", "close", "tick_volume", "spread");
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   for(int i = 0; i < copied; i++)
   {
      FileWrite(h,
                TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES),
                DoubleToString(rates[i].open, digits),
                DoubleToString(rates[i].high, digits),
                DoubleToString(rates[i].low, digits),
                DoubleToString(rates[i].close, digits),
                (string)rates[i].tick_volume,
                (string)rates[i].spread);
   }
   FileClose(h);
   PrintFormat("%s %s: %d barras exportadas", sym, TfName(tf), copied);
   return true;
}

void OnStart()
{
   string syms[];
   int n = StringSplit(InpSymbols, ',', syms);
   string meta = InpFolder + "\\symbols_meta.csv";
   int hm = FileOpen(meta, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(hm != INVALID_HANDLE)
      FileWrite(hm, "symbol", "point", "digits", "contract_size", "swap_long", "swap_short",
                "swap_mode", "currency_profit");

   for(int k = 0; k < n; k++)
   {
      string sym = syms[k];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      if(sym == "")
         continue;
      if(!SymbolSelect(sym, true))
      {
         PrintFormat("Ativo não encontrado na corretora: %s", sym);
         continue;
      }
      if(InpD1) ExportOne(sym, PERIOD_D1);
      if(InpH4) ExportOne(sym, PERIOD_H4);
      if(InpH1) ExportOne(sym, PERIOD_H1);
      if(hm != INVALID_HANDLE)
         FileWrite(hm, sym,
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 10),
                   (string)SymbolInfoInteger(sym, SYMBOL_DIGITS),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE), 2),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_LONG), 4),
                   DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), 4),
                   (string)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE),
                   SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT));
   }
   if(hm != INVALID_HANDLE)
      FileClose(hm);
   Print("Exportação concluída. Pasta: MQL5/Files/", InpFolder);
}
//+------------------------------------------------------------------+
