import express, { Request, Response } from 'express';
import { GoogleGenAI } from '@google/genai';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ai = new GoogleGenAI({
  apiKey: process.env.GEMINI_API_KEY,
  httpOptions: {
    headers: {
      'User-Agent': 'aistudio-build',
    },
  },
});

async function startServer() {
  const app = express();
  app.use(express.json());

  // API endpoint for structuring and optimizing Python Telegram Bot code
  app.post('/api/generate', async (req: Request, res: Response) => {
    try {
      const { prompt, currentCode, library, botType } = req.body;

      const systemInstruction = `You are an expert Python Telegram Bot Developer. 
Your goal is to optimize, organize, structure, and document Python Telegram Bot code.
The user speaks Bengali/Bangla, so all explanations, setup instructions, and code comments MUST be written in beautiful, clear, natural, and helpful Bengali (Bangla/বাংলা) with relevant English technical terms.
Make sure the generated code is:
1. Production-ready, clean, secure, and robust.
2. Uses standard, secure environment variable configuration (NEVER hardcode API keys or bots token, default to getting them via os.getenv("TELEGRAM_BOT_TOKEN") and explain how to create a .env file).
3. Utilizes proper Python logging framework (logging.basicConfig) with standard stream handlers so errors can be easily caught in terminal.
4. Uses correct library patterns:
   - For "python-telegram-bot": Use latest V20+ async/await implementation using ApplicationBuilder, CommandHandler, MessageHandler, filters, and ContextTypes.DEFAULT_TYPE. Ensure context arguments and callback_queries are treated properly.
   - For "pyTelegramBotAPI" (telebot): Use TeleBot, telebot.types, message_handler decorators, and standard polling.

Your reply MUST be formatted in clean Markdown, containing:
1. A brief welcoming or encouraging message in Bengali (e.g. "আসসালামু আলাইকুম! আপনার টেলিগ্রাম বটের কোডটি সাজিয়ে দেওয়া হলো...").
2. The revised/arranged Python Code inside a single clean \`\`\`python ... \`\`\` code block with extensive inline comments in Bengali.
3. A clear, step-by-step description of what was added/fixed and how to run the bot on their computer (install dependencies via pip, set up environment variables or a .env file, and launch the script) written in beautiful Bangla.`;

      const contents = `
Chose Library: ${library}
Bot Type Goal: ${botType}
Explanation Language: Bengali

User's Request/Prompt or code fix request:
"${prompt}"

User's original Python code to arrange/optimize:
\`\`\`python
${currentCode || '# No code provided yet. Please build from scratch.'}
\`\`\`
      `;

      const response = await ai.models.generateContent({
        model: 'gemini-3.5-flash',
        contents,
        config: {
          systemInstruction,
          temperature: 0.1,
        },
      });

      res.json({ text: response.text });
    } catch (error: any) {
      console.error('Error generating content', error);
      res.status(500).json({ error: error.message || 'Error occurred while talking to Gemini.' });
    }
  });

  // API endpoint for simulating the bot behaviors
  app.post('/api/simulate', async (req: Request, res: Response) => {
    try {
      const { userMessage, botCode, botType, library, chatHistory } = req.body;

      const contents = [];
      
      const systemInstruction = `You are a simulated Telegram Bot running inside a virtual chat mock in are React workspace.
Your task is to analyze the provided Python Telegram Bot code and act EXACTLY like that bot would respond if the user messaged it on Telegram.
- Look at the commands defined in the source code (such as /start, /help, /register, etc.). If the user sends these commands (or similar text), respond exactly as the Python code tells the bot to.
- Simualate the buttons/keyboards if the bot defines ReplyKeyboard or InlineKeyboard buttons. Mention choices or options in standard textual representation first or respond if user picks them.
- Keep the messages relatively short, friendly, and in the language of the bot code (e.g. if the bot replies in Bangla, reply in Bangla; if in English, reply in English).
- Do not output Python code or explain anything technical. Just reply with the chat bubble text that the bot itself would send back to a Telegram user.
- If the user types a command that is not handled in the code, reply with how the bot handles fallbacks (or a friendly Telegram bot response indicating unknown command in Bangla/English).

=== BOT CONTRACT / SOURCE CODE ===
Library Target: ${library || 'Unknown'}
Bot Core Focus: ${botType || 'General'}
${botCode || '# No bot code written yet. Act as a default friendly bot greeting the user in Bangla & English.'}
==================================`;

      // Build contents
      if (chatHistory && Array.isArray(chatHistory)) {
        for (const historyItem of chatHistory) {
          contents.push({
            role: historyItem.role === 'bot' ? 'model' : 'user',
            parts: [{ text: historyItem.text }],
          });
        }
      }
      contents.push({
        role: 'user',
        parts: [{ text: userMessage }],
      });

      const response = await ai.models.generateContent({
        model: 'gemini-3.5-flash',
        contents,
        config: {
          systemInstruction,
          temperature: 0.4,
        },
      });

      res.json({ text: response.text });
    } catch (error: any) {
      console.error('Simulation Error', error);
      res.status(500).json({ error: error.message || 'Error executing simulation.' });
    }
  });

  // Serve static assets or run with Vite
  if (process.env.NODE_ENV === 'production') {
    app.use(express.static(path.join(__dirname, 'dist')));
    app.get('*', (req: Request, res: Response) => {
      res.sendFile(path.join(__dirname, 'dist', 'index.html'));
    });
  } else {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  }

  const port = 3000;
  app.listen(port, '0.0.0.0', () => {
    console.log(`Telegram Bot Creator server running on http://0.0.0.0:${port}`);
  });
}

startServer();
