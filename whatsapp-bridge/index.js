const express = require("express");
const pino = require("pino");
const QRCode = require("qrcode");
const qrcodeTerminal = require("qrcode-terminal");
const fs = require("fs");
const path = require("path");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");

const PORT = process.env.WA_BRIDGE_PORT || 3001;
const FASTAPI_PORT = process.env.PORT || 8000;
const PYTHON_API_URL =
  process.env.PYTHON_API_URL || `http://127.0.0.1:${FASTAPI_PORT}`;
const AUTH_DIR = path.join(__dirname, "auth_info_baileys");
const CREDS_FILE = path.join(AUTH_DIR, "creds.json");

const app = express();
app.use(express.json({ limit: "2mb" }));

let sock = null;
let connectionState = "connecting"; // connecting | qr_ready | connected | disconnected
let currentQrDataUrl = null;
let connectedUser = null;
let isStarting = false;
let reconnectTimer = null;

const processedMsgIds = new Set();
// Armazena as mensagens enviadas para que o getMessage reenvie o conteúdo real
// caso o celular mostre "Aguardando mensagem. Essa ação pode levar alguns instantes."
const sentMessagesStore = new Map();
// Cache de metadados de grupos para envio instantâneo sem falha de criptografia
const groupMetadataCache = new Map();

function normalizeText(str) {
  return (str || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

function loadCachedUserFromDisk() {
  try {
    if (fs.existsSync(CREDS_FILE)) {
      const raw = JSON.parse(fs.readFileSync(CREDS_FILE, "utf-8"));
      if (raw && raw.me && raw.me.id) {
        connectedUser = raw.me;
        connectionState = "connected";
        return true;
      }
    }
  } catch (_) {}
  return false;
}

loadCachedUserFromDisk();

async function fetchAllGroups() {
  if (!sock) return [];
  try {
    const groupsObj = await sock.groupFetchAllParticipating();
    const list = Object.values(groupsObj || {});
    for (const g of list) {
      if (g && g.id) {
        groupMetadataCache.set(g.id, g);
      }
    }
    return list.map((g) => ({
      id: g.id,
      name: g.subject || "Grupo sem nome",
      participants: (g.participants || []).length,
    }));
  } catch (err) {
    console.error("[WhatsApp] Erro ao buscar grupos:", err.message);
    return [];
  }
}

const FIXED_DEFAULT_TARGET = "bot de dolar";

function isBotDeDolarGroup(subject) {
  if (!subject) return false;
  const norm = normalizeText(subject);
  if (norm === "bot de dolar" || norm === "bot dolar") return true;
  const clean = norm.replace(/[^a-z0-9]/g, "");
  return clean === "botdedolar" || clean === "botdolar" || clean === "botdodolar";
}

async function resolveTargetJid(targetInput) {
  let raw = (targetInput || "").trim();
  if (!raw || isBotDeDolarGroup(raw)) {
    raw = FIXED_DEFAULT_TARGET;
  }

  // 1. Se já for um JID explícito de grupo ou contato
  if (raw.endsWith("@g.us") || raw.endsWith("@s.whatsapp.net")) {
    return raw;
  }

  // 2. Se tiver letras (ex: "bot de dolar", "bot dolar"), procura nos grupos pelo nome!
  const hasLetters = /[a-zA-ZÀ-ÿ]/.test(raw);
  if (hasLetters) {
    const groups = await fetchAllGroups();

    // 1. Prioriza correspondência com o grupo oficial "bot de dolar"
    if (isBotDeDolarGroup(raw)) {
      const matchedOfficial = groups.find((g) => isBotDeDolarGroup(g.name));
      if (matchedOfficial) {
        return matchedOfficial.id;
      }
    }

    const searchName = normalizeText(raw);

    // 2. Busca exata (ignorando acentos e maiúsculas)
    let matched = groups.find((g) => normalizeText(g.name) === searchName);
    // 3. Busca parcial (contém o nome)
    if (!matched) {
      matched = groups.find((g) => normalizeText(g.name).includes(searchName));
    }
    // 4. Busca flexível ignorando conectivos ("de", "do", "da", "grupo")
    if (!matched) {
      const cleanSearch = searchName
        .replace(/\b(de|do|da|grupo)\b/g, "")
        .replace(/\s+/g, " ")
        .trim();
      matched = groups.find((g) => {
        const cleanName = normalizeText(g.name)
          .replace(/\b(de|do|da|grupo)\b/g, "")
          .replace(/\s+/g, " ")
          .trim();
        return cleanName.includes(cleanSearch) || cleanSearch.includes(cleanName);
      });
    }

    if (matched) {
      return matched.id;
    }

    const availableNames = groups.map((g) => `"${g.name}"`).join(", ");
    throw new Error(
      `Grupo "${raw}" não encontrado! Grupos detectados: ${availableNames || "nenhum grupo encontrado"}. Crie um grupo no WhatsApp chamado "bot de dolar".`
    );
  }

  // 3. Caso seja número de telefone
  let digits = raw.replace(/\D/g, "");
  // Se digitou apenas DDD + número (10 ou 11 dígitos, ex: 19999831973), adiciona o DDI 55 do Brasil
  if ((digits.length === 10 || digits.length === 11) && !digits.startsWith("55")) {
    digits = "55" + digits;
  }

  const jid = `${digits}@s.whatsapp.net`;
  if (sock) {
    try {
      const [res] = await sock.onWhatsApp(jid);
      if (res && res.exists) return res.jid;
    } catch (_) {}
  }
  return jid;
}

async function sendSafeMessage(targetJid, text) {
  if (!sock) throw new Error("Socket do WhatsApp não inicializado.");

  // Se for grupo, garante que os metadados dos participantes estão em cache antes de criptografar
  if (targetJid.endsWith("@g.us") && !groupMetadataCache.has(targetJid)) {
    try {
      const meta = await sock.groupMetadata(targetJid);
      if (meta) groupMetadataCache.set(targetJid, meta);
    } catch (_) {}
  }

  const sent = await sock.sendMessage(targetJid, { text });
  if (sent && sent.key && sent.key.id && sent.message) {
    sentMessagesStore.set(sent.key.id, sent.message);
    if (sentMessagesStore.size > 500) {
      const oldestKey = sentMessagesStore.keys().next().value;
      sentMessagesStore.delete(oldestKey);
    }
  }
  return sent;
}

function extractMessageText(messageObj) {
  if (!messageObj) return "";
  const inner =
    messageObj.ephemeralMessage?.message ||
    messageObj.viewOnceMessage?.message ||
    messageObj.documentWithCaptionMessage?.message ||
    messageObj;

  return (
    inner.conversation ||
    inner.extendedTextMessage?.text ||
    inner.imageMessage?.caption ||
    ""
  );
}

async function resolveReplyJid(remoteJid, fromMe) {
  // Se a mensagem veio de um grupo (@g.us), responde diretamente no próprio grupo!
  if (remoteJid && remoteJid.endsWith("@g.us")) {
    return remoteJid;
  }
  // Se veio do chat próprio (@lid), tenta achar primeiro o grupo "bot de dolar" ou usa @s.whatsapp.net
  if (fromMe && remoteJid && remoteJid.endsWith("@lid")) {
    try {
      const jid = await resolveTargetJid("");
      if (jid) return jid;
    } catch (_) {}
  }
  return remoteJid;
}

async function startWhatsApp() {
  if (isStarting) return;
  isStarting = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  try {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    if (state.creds && state.creds.me && state.creds.me.id) {
      connectedUser = state.creds.me;
      connectionState = "connected";
      currentQrDataUrl = null;
    }

    let version = [2, 3000, 1015901307];
    try {
      const latest = await fetchLatestBaileysVersion();
      if (latest && latest.version) version = latest.version;
    } catch (_) {}

    if (sock) {
      try {
        sock.ev.removeAllListeners();
        sock.ws?.close();
      } catch (_) {}
    }

    sock = makeWASocket({
      version,
      logger: pino({ level: "silent" }),
      printQRInTerminal: false,
      auth: state,
      browser: ["Smart Dollar Bot", "Chrome", "120.0.0"],
      syncFullHistory: false,
      keepAliveIntervalMs: 25000,
      retryRequestDelayMs: 250,
      maxMsgRetryCount: 10,
      cachedGroupMetadata: async (jid) => groupMetadataCache.get(jid),
      // Retorna a mensagem real armazenada para destravar "Aguardando mensagem..." no celular!
      getMessage: async (key) => {
        if (key && key.id && sentMessagesStore.has(key.id)) {
          return sentMessagesStore.get(key.id);
        }
        return { conversation: "💵 Smart Dollar Bot" };
      },
    });

    let backupTimer = null;
    function schedulePythonWaBackup() {
      if (backupTimer) clearTimeout(backupTimer);
      backupTimer = setTimeout(() => {
        fetch(`${PYTHON_API_URL}/api/internal/wa-backup`, {
          method: "POST",
        }).catch(() => {});
      }, 2500);
    }

    sock.ev.on("creds.update", async () => {
      await saveCreds();
      if (sock?.user?.id) {
        connectedUser = sock.user;
      }
      schedulePythonWaBackup();
    });

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        connectionState = "qr_ready";
        console.log("\n=======================================================");
        console.log("📱 ESCANEIE O QR CODE ABAIXO NO SEU WHATSAPP");
        console.log("   (Ou abra http://localhost:8000 no navegador)");
        console.log("=======================================================\n");
        qrcodeTerminal.generate(qr, { small: true });
        try {
          currentQrDataUrl = await QRCode.toDataURL(qr, {
            margin: 2,
            width: 520,
          });
        } catch (err) {
          console.error("Erro ao gerar QR DataURL:", err.message);
        }
      }

      if (connection === "close") {
        const statusCode =
          lastDisconnect?.error?.output?.statusCode ||
          lastDisconnect?.error?.statusCode;
        const isLoggedOut = statusCode === DisconnectReason.loggedOut;

        console.log(
          `[WhatsApp] Conexão oscilou (código: ${statusCode}). Reconectando automaticamente...`
        );

        if (!isLoggedOut) {
          if (!loadCachedUserFromDisk()) {
            connectionState = "connecting";
          }
          if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              isStarting = false;
              startWhatsApp();
            }, 3000);
          }
        } else {
          connectionState = "disconnected";
          connectedUser = null;
          currentQrDataUrl = null;
          if (fs.existsSync(AUTH_DIR)) {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
          }
          reconnectTimer = setTimeout(() => {
            isStarting = false;
            startWhatsApp();
          }, 2000);
        }
      } else if (connection === "open") {
        connectionState = "connected";
        currentQrDataUrl = null;
        connectedUser = sock.user || connectedUser || {};
        const bareNumber = (connectedUser.id || "").split(":")[0].split("@")[0];
        console.log("\n=======================================================");
        console.log(`✅ WHATSAPP CONECTADO E ATIVO! Número: +${bareNumber}`);
        console.log("💡 Dica: Crie um grupo chamado 'bot de dolar' e mande !dolar nele!");
        console.log("=======================================================\n");
        schedulePythonWaBackup();
        // Pré-carrega os grupos em cache
        setTimeout(fetchAllGroups, 1500);
      }
    });

    sock.ev.on("groups.update", async (updates) => {
      for (const update of updates) {
        if (update && update.id) {
          const cached = groupMetadataCache.get(update.id) || {};
          groupMetadataCache.set(update.id, { ...cached, ...update });
        }
      }
    });

    sock.ev.on("messages.upsert", async ({ messages, type }) => {
      if (type !== "notify" && type !== "append") return;

      for (const msg of messages) {
        if (!msg.message || !msg.key) continue;

        const msgId = msg.key.id;
        if (msgId && processedMsgIds.has(msgId)) continue;
        // Ignora mensagens que o próprio bot acabou de enviar
        if (msgId && sentMessagesStore.has(msgId)) continue;

        const msgTs = Number(msg.messageTimestamp || 0);
        const nowSec = Math.floor(Date.now() / 1000);
        if (msgTs > 0 && nowSec - msgTs > 45) continue;

        const text = extractMessageText(msg.message);
        const trimmed = text.trim();
        // Ignora se não começar com '!' seguido de letra ou dígito (ex: ignora '!', '!!', '!!!')
        if (!/^![a-zA-Z0-9À-ÿ]/.test(trimmed)) continue;

        const remoteJid = msg.key.remoteJid;
        if (!remoteJid || remoteJid === "status@broadcast") continue;

        // REGRA DE SEGURANÇA E MONITORAMENTO EXCLUSIVO:
        // O bot só atende se a mensagem for enviada no grupo "bot de dolar".
        // Mensagens diretas (PV/chat privado) ou em qualquer outro grupo são completamente ignoradas!
        if (!remoteJid.endsWith("@g.us")) {
          console.log(
            `[WhatsApp Ignorado] Comando "${trimmed}" ignorado pois veio de chat privado (${remoteJid}). O bot só atende no grupo "bot de dolar".`
          );
          continue;
        }

        // Obtém metadados do grupo para validar o nome
        let groupMeta = groupMetadataCache.get(remoteJid);
        if (!groupMeta && sock) {
          try {
            groupMeta = await sock.groupMetadata(remoteJid);
            if (groupMeta) {
              groupMetadataCache.set(remoteJid, groupMeta);
            }
          } catch (metaErr) {
            console.error(`[WhatsApp] Não foi possível obter metadados do grupo ${remoteJid}:`, metaErr.message);
          }
        }

        const groupSubject = groupMeta?.subject || "";
        if (!isBotDeDolarGroup(groupSubject)) {
          console.log(
            `[WhatsApp Ignorado] Comando "${trimmed}" ignorado no grupo "${groupSubject || remoteJid}". O bot opera EXCLUSIVAMENTE no grupo "bot de dolar".`
          );
          continue;
        }

        if (msgId) {
          processedMsgIds.add(msgId);
          if (processedMsgIds.size > 500) {
            const first = processedMsgIds.values().next().value;
            processedMsgIds.delete(first);
          }
        }

        console.log(`[WhatsApp Comando Aceito] "${trimmed}" no grupo "${groupSubject}" (${remoteJid})`);
        try {
          const resp = await fetch(`${PYTHON_API_URL}/api/whatsapp/command`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              command: trimmed,
              sender: remoteJid,
              group_name: groupSubject,
            }),
          });
          if (resp.ok) {
            const data = await resp.json();
            if (data.reply) {
              await sendSafeMessage(remoteJid, data.reply);
              console.log(`[WhatsApp Resposta Enviada] -> ${groupSubject} (${remoteJid})`);
            }
          }
        } catch (err) {
          console.error("[WhatsApp] Erro ao processar comando:", err.message);
        }
      }
    });
  } catch (err) {
    console.error("[WhatsApp] Erro ao iniciar Baileys:", err.message);
    if (!loadCachedUserFromDisk()) {
      connectionState = "disconnected";
    }
    reconnectTimer = setTimeout(() => {
      isStarting = false;
      startWhatsApp();
    }, 5000);
  } finally {
    isStarting = false;
  }
}

app.get("/status", (req, res) => {
  if (!connectedUser) {
    loadCachedUserFromDisk();
  }
  const bareNumber = connectedUser?.id
    ? connectedUser.id.split(":")[0].split("@")[0]
    : null;

  const effectiveStatus =
    bareNumber && connectionState !== "qr_ready" ? "connected" : connectionState;

  res.json({
    status: effectiveStatus,
    qr_data_url: effectiveStatus === "connected" ? null : currentQrDataUrl,
    user_phone: bareNumber,
    user_name: connectedUser?.name || null,
  });
});

app.get("/groups", async (req, res) => {
  const groups = await fetchAllGroups();
  res.json({ ok: true, groups });
});

app.post("/send", async (req, res) => {
  const { phone, message } = req.body || {};
  if (!sock) {
    return res.status(400).json({
      ok: false,
      error: "WhatsApp ainda não está pronto. Aguarde alguns segundos.",
    });
  }

  try {
    const targetJid = await resolveTargetJid(phone);
    if (!targetJid) {
      return res.status(400).json({
        ok: false,
        error: "Destino inválido e nenhum grupo ou número conectado encontrado.",
      });
    }

    await sendSafeMessage(targetJid, message);
    return res.json({ ok: true, target: targetJid });
  } catch (err) {
    console.error("[WhatsApp] Falha ao enviar mensagem:", err.message);
    return res.status(400).json({ ok: false, error: err.message });
  }
});

app.post("/logout", async (req, res) => {
  try {
    if (sock) {
      await sock.logout();
    }
  } catch (_) {}
  if (fs.existsSync(AUTH_DIR)) {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
  }
  connectionState = "connecting";
  currentQrDataUrl = null;
  connectedUser = null;
  isStarting = false;
  setTimeout(startWhatsApp, 1000);
  res.json({ ok: true });
});

const server = app.listen(PORT, "127.0.0.1", () => {
  console.log(`🚀 Ponte WhatsApp Web (Baileys) rodando em http://127.0.0.1:${PORT}`);
  startWhatsApp();
});

server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    console.log(`[WhatsApp Bridge] Porta ${PORT} já está em uso por outra instância ativa. Encerrando duplicata.`);
    process.exit(0);
  }
});
