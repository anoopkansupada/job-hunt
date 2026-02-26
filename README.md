# Job Hunt Optimizer

Resume and cover letter optimization powered by Claude.

## Quick Start (Local Network)

### 1. Get Your API Key
- Go to https://console.anthropic.com/
- Create/copy your API key
- Create `.env.local` file in this directory:
  ```bash
  cp .env.local.example .env.local
  # Edit .env.local and paste your ANTHROPIC_API_KEY
  ```

### 2. Start the Dev Server
```bash
npm run dev
```

Server runs on `http://localhost:3000`

### 3. Access from Same Network
On Catrina's device (same WiFi):
- Find your Mac's local IP: `ipconfig getifaddr en0` or `ipconfig getifaddr en1`
- Visit: `http://YOUR_IP:3000`

Example: `http://192.168.1.100:3000`

---

## Features

**5 Optimization Strategies:**
1. **Resume Tailoring** - Match resume to specific job description
2. **Resume Audit** - Identify gaps and get revision suggestions  
3. **Bullet Generator** - Convert achievements to strong bullet points
4. **Cover Letter** - Generate role-specific cover letter
5. **Keywords Mapping** - Map skills to job requirements

**Streaming Output** - See Claude's response in real-time

---

## Architecture

- **Frontend**: React 18 + Next.js 14 + Tailwind CSS
- **Backend**: Next.js API routes
- **LLM**: Claude 3.5 Sonnet (via Anthropic API)

All processing happens locally on your Mac. Everything is private and fast.

---

## Optional: Tailscale Remote Access

To access from outside your home network:

1. Both you and Catrina have Tailscale installed
2. In a terminal (from this app directory):
   ```bash
   # Get your Tailscale magic DNS
   tailscale ip -4
   # e.g., 100.80.53.56
   
   # Or get the DNS name
   hostname
   # Then construct: https://[hostname].taila85053.ts.net:3000
   ```

3. Catrina can then access: `https://jarviss-mac-mini.taila85053.ts.net:3000`

---

## Troubleshooting

**"ANTHROPIC_API_KEY not configured"**
- Check that `.env.local` file exists
- Verify you pasted your API key correctly
- Restart the dev server after adding the key

**Can't access from other device**
- Verify both devices are on same WiFi
- Check your local IP with: `ipconfig getifaddr en0`
- Make sure the dev server is still running
- Try disabling firewall temporarily (or add Next.js to allowlist)

---

## Building for Production

```bash
npm run build
npm run start
```

Runs on port 3000. Use with a reverse proxy (nginx, Vercel, etc.) for production.
