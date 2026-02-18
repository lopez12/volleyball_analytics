# Volleyball Analytics

A web-based volleyball analytics dashboard that runs entirely in your browser. Perfect for GitHub Pages deployment!

## Features

- ✅ **100% Client-Side** - No server required, works on GitHub Pages
- 📊 Parse volleyball match logs
- 📈 Calculate player and team statistics  
- 🎯 Generate detailed performance reports
- 📄 Export reports to PDF
- 🌐 Import match data from GitHub

## Quick Start

**Just open `index.html` in your browser - that's it!**

No installation, no setup, no servers. Everything runs in your browser.

## Tech Stack

- HTML/CSS/JavaScript (vanilla)
- html2pdf.js for PDF generation
- Pure client-side processing

## Deployment to GitHub Pages

1. Push this repository to GitHub
2. Go to Settings → Pages
3. Select your branch (usually `main`)
4. Click Save
5. Your site will be live at `https://yourusername.github.io/volleyball_analytics`

## Usage

1. **Enter Match Data:**
   - Paste volleyball match log in the text area
   - Format: `[PlayerNumber][Action][Grade]` (e.g., `7S# 10R! 2E+ 7A-`)

2. **Generate Report:**
   - Click "📊 Generar Reporte" button
   - The dashboard will display player statistics, team performance, and ratings

3. **Import from GitHub:**
   - Click "🌐 Importar desde GitHub" to load match files from the repository

4. **Export PDF:**
   - Click "📄 Descargar PDF" to download the report

## Match Log Format

### Actions

- `S` - Saque (Serve)
- `R` - Recepción de Saque (Reception)
- `E` - Acomodo (Set)
- `A` - Ataque (Attack)
- `D` - Defensa (Defense)
- `B` - Bloqueo (Block)

### Grades

- `#` - Perfecto (Perfect) - +1.0 points
- `+` - Positivo (Positive) - +0.4 points
- `!` - Regular (Regular) - -0.3 points
- `-` - Error (Error) - -1.0 points

### Examples

- `7S#` - Player 7, Serve, Perfect
- `10R!` - Player 10, Reception, Regular
- `2E+` - Player 2, Set, Positive
- `7A-` - Player 7, Attack, Error
- `S#` - Team serve (no player number)

## Project Structure

```txt
volleyball_analytics/
├── index.html             # Main HTML file
├── main.js                # All parsing and UI logic
├── styles.css             # Styles
├── vodkas_vs_atlas.txt    # Sample match data
├── README.md              # This file
└── app.py*                # (Optional) Experimental Python backend
└── requirements.txt*      # (Optional) Python dependencies
```

*Python files are experimental and not needed for the main application.

## Local Development

Simply open `index.html` in any modern browser. For a better development experience:

### Using VS Code:

Install the "Live Server" extension and right-click `index.html` → "Open with Live Server"

## How It Works

All processing happens in JavaScript:

1. User pastes match log
2. `parseLog()` function parses the text
3. `calculateRating()` computes player ratings (1-10 scale)
4. Report is generated dynamically in the browser
5. html2pdf.js converts the HTML to PDF when exporting

No data leaves your browser!

## Troubleshooting

### PDF not generating?

Make sure you have an internet connection (html2pdf.js loads from CDN)

### GitHub Pages not updating?

- Check GitHub Actions tab for deployment status
- Clear your browser cache
- Wait a few minutes for propagation

## Optional: Python Backend (Experimental)

There's an experimental Python Flask backend in `app.py` if you want to explore server-side processing:

```bash
pip install -r requirements.txt
python app.py
```

But it's **not required** for the main application and won't work on GitHub Pages.

## License

MIT License
