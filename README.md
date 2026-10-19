# 💵 Smart Dollar Watcher — Motor Quantitativo 4 Pilares + Bot WhatsApp

Sistema completo em **Python (FastAPI + Pandas/NumPy)** integrado com **WhatsApp Web Local (Baileys)** e **Dashboard Web em Tempo Real** para monitorar a cotação do dólar (`USD/BRL`) e avisar no WhatsApp **apenas quando realmente compensa comprar**.

---

## 🧠 Como o Sistema Decide se "Realmente Compensa"? (Score 0 a 100)

Em vez de olhar apenas se o dólar caiu alguns centavos no dia, o motor quantitativo ([`analyze_dollar`](file:///c:/Users/supervisor/Documents/antigravity/hopeful-lavoisier/app/analyzer.py#L28-L353)) calcula uma nota de **0 a 100** combinando **4 pilares**:

1. **📐 Estatística Histórica (até 35 pontos)**
   - **Percentil de 30 e 90 dias:** Verifica que porcentagem dos últimos 30 e 90 dias teve fechamento mais caro que o preço atual (ex.: *"Mais barato que 90% dos últimos 30 dias"*).
   - **Z-Score ($Z = \frac{P - \mu}{\sigma}$):** Mede quantos desvios-padrão o dólar atual está abaixo da média de 30 e 90 dias.

2. **📈 Indicadores Técnicos (até 35 pontos)**
   - **RSI (Índice de Força Relativa - 14 períodos):** Detecta quando a moeda está em sobrevenda ($\text{RSI} < 35$) ou sobrecompra ($\text{RSI} > 65$).
   - **Bandas de Bollinger (20 períodos, $2\sigma$):** Calcula a posição percentual (`%B`) do dólar dentro do canal de volatilidade. Preços próximos da banda inferior indicam forte desconto estatístico.
   - **Médias Móveis (`EMA 9`, `SMA 20`, `SMA 50`, `SMA 90`):** Avalia o desconto percentual em relação às tendências curta, média e longa.

3. **🛡️ Timing, Volatilidade & Filtro "Anti-Faca Caindo" (até 20 pontos)**
   - **MACD (12, 26, 9) + Inércia do Histograma:** Identifica se o dólar está despencando em queda livre acelerada (**"Faca Caindo"**) ou se a força vendedora já está desacelerando perto de um suporte (**"Fundo Provável"**).
   - **ATR (Average True Range - 14 períodos):** Mede a volatilidade diária em R$ e sugere **compra escalonada em lotes (DCA)** (ex.: comprar 50% agora e 50% se recuar mais $0.65 \times \text{ATR}$).

4. **💳 Simulador Real de Custo Efetivo — VET (até 10 pontos)**
   - Calcula o custo real final no bolso somando **Cotação Comercial + Spread + IOF** em 4 modalidades:
     - **Conta Global Viagem (Wise / Nomad / Inter):** Spread `0.90%` + IOF `1.10%`
     - **Conta Global Investimento:** Spread `0.90%` + IOF `0.38%`
     - **Espécie (Casa de Câmbio):** Spread `4.20%` + IOF `1.10%`
     - **Cartão de Crédito Tradicional:** Spread `4.50%` + IOF `3.38%`
   - Mostra exatamente **quantos Reais (R$) você economiza** comprando hoje vs. a média e o topo dos últimos 30 dias.

---

## 🚀 Como Iniciar

Basta dar dois cliques no arquivo [`iniciar.bat`](file:///c:/Users/supervisor/Documents/antigravity/hopeful-lavoisier/iniciar.bat) ou rodar no terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Depois, acesse o **Painel Web**:
👉 **http://localhost:8000**

1. Na primeira vez, escaneie o **QR Code do WhatsApp** (que aparece tanto no Painel Web quanto no terminal).
2. Clique em **"📲 Enviar Raio-X no Zap Agora"** para receber um teste imediato!

---

## 💬 Comandos Interativos no WhatsApp

Você pode mandar mensagens no próprio WhatsApp (inclusive na conversa com você mesmo) usando:

- `!dolar` ou `!agora` — Recebe o Raio-X completo da cotação e Score na hora
- `!simular 2000` — Simula a compra de US$ 2.000 com taxas reais (Wise/Nomad/Espécie/Cartão)
- `!meta 5.45` — Cria um alerta caso o dólar caia para R$ 5,45 ou menos (`!meta off` para desativar)
- `!score 75` — Altera a nota mínima (0-100) para disparo de alertas automáticos
- `!ajuda` — Lista todos os comandos disponíveis
