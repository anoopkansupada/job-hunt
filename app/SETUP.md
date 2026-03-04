# Setup Instructions

## Step 1: Get Your Anthropic API Key

1. Go to https://console.anthropic.com/
2. Click "API Keys" in the left sidebar
3. Create a new API key or copy an existing one
4. Keep it safe (don't share or commit to git)

## Step 2: Configure the App

### Option A: Quick Setup (One Command)
```bash
# In the app directory, run:
echo "ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE" > .env.local
# Replace YOUR_KEY_HERE with your actual API key
```

### Option B: Manual Setup
```bash
# Copy the example file
cp .env.local.example .env.local

# Edit .env.local with your editor:
# ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
```

## Step 3: Start the Server

```bash
npm run dev
```

You should see:
```
▲ Next.js 14.1.4
- Local:        http://localhost:3000
✓ Ready in Xms
```

## Step 4: Test It

Open http://localhost:3000 in your browser. You should see the app.

## Step 5: Share with Catrina

**If on same WiFi:**
```bash
# Find your local IP
ipconfig getifaddr en0
# Example output: 192.168.1.100

# Share this URL with Catrina:
# http://192.168.1.100:3000
```

**If using Tailscale:**
```bash
# Get your Tailscale IP
tailscale ip -4
# Example: 100.80.53.56

# Construct the magic DNS name and share:
# https://jarviss-mac-mini.taila85053.ts.net:3000
```

## Done! 🎉

The app is now ready for Catrina to use.

---

## Notes

- The server must stay running while using the app
- API calls use your Anthropic credits (Claude 3.5 Sonnet)
- Each optimization costs ~0.50-1.00 credits depending on length
- Output is streamed in real-time (you'll see it appear as Claude generates)
