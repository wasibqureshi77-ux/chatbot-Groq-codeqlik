const express = require("express");
const cors = require("cors");
const nodemailer = require("nodemailer");
require("dotenv").config();

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 9000;
const MAIL_SERVICE_SECRET = process.env.MAIL_SERVICE_SECRET || "change_this_internal_secret";
const SMTP_HOST = process.env.SMTP_HOST;
const SMTP_PORT = parseInt(process.env.SMTP_PORT || "587", 10);
const SMTP_USER = process.env.SMTP_USER;
const SMTP_PASS = process.env.SMTP_PASS;
const FROM_EMAIL = process.env.FROM_EMAIL || "no-reply@example.com";
const FROM_NAME = process.env.FROM_NAME || "Chatbot Mail Service";

if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) {
  console.warn("[mail-service] Missing SMTP configuration in .env. Set SMTP_HOST, SMTP_USER, and SMTP_PASS.");
}

const transporter = nodemailer.createTransport({
  host: SMTP_HOST,
  port: SMTP_PORT,
  secure: SMTP_PORT === 465,
  auth: {
    user: SMTP_USER,
    pass: SMTP_PASS,
  },
});

app.get("/", (req, res) => {
  res.json({ status: "ok", message: "Mail service is running." });
});

app.post("/send-email", async (req, res) => {
  const secretHeader = req.headers["x-mail-service-secret"] || req.headers["x-mail-service-key"];
  if (secretHeader !== MAIL_SERVICE_SECRET) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const { to, subject, html, text, fromEmail, fromName } = req.body;
  if (!to || !subject || (!html && !text)) {
    return res.status(400).json({ error: "Missing required fields: to, subject, and html or text." });
  }

  const mailOptions = {
    from: `${fromName || FROM_NAME} <${fromEmail || FROM_EMAIL}>`,
    to,
    subject,
    text: text || undefined,
    html: html || undefined,
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    return res.json({ success: true, messageId: info.messageId });
  } catch (error) {
    console.error("[mail-service] sendMail error:", error);
    return res.status(500).json({ error: "Failed to send email", details: error.message || error.toString() });
  }
});

app.listen(PORT, () => {
  console.log(`[mail-service] Listening on port ${PORT}`);
  console.log(`[mail-service] SMTP host: ${SMTP_HOST || "(not configured)"}`);
});
