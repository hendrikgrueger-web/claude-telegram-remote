# Setup-Prompt für Claude Code auf dem Mac mini

Kopiere alles zwischen den `---` Trennlinien und füge es in Claude Code ein:

---

Ich möchte den Claude Telegram Remote Control Bot einrichten.

Das Repository liegt bereits geklont unter: `~/Coding/4_claude/remote-control-telegram/`
(Falls abweichend, passe den Pfad an.)

Bitte führe folgende Schritte der Reihe nach durch:

1. Wechsle ins Verzeichnis: `~/Coding/4_claude/remote-control-telegram/`
2. Prüfe die Python-Version: muss 3.10 oder neuer sein
3. Mache install.sh ausführbar und starte es: `chmod +x install.sh && bash install.sh`
4. Begleite mich interaktiv durch die Konfiguration (.env — Telegram Token, User-ID, Verzeichnis)
5. Stelle sicher, dass workspaces.json korrekt angelegt wurde: `cat ~/.config/claude-telegram/workspaces.json`
6. Prüfe ob der launchd Service läuft: `launchctl list | grep claude-telegram`
7. Zeige die letzten Zeilen des Logs: `tail -20 ~/Library/Logs/claude-telegram/bot.log`
8. Erinnere mich: Auto-Login muss aktiviert sein (Systemeinstellungen → Allgemein → Autom. Anmelden)
9. Teste den Bot: Schicke mir eine kurze Nachricht über Telegram und bestätige, dass eine Antwort kommt

Falls ein Schritt fehlschlägt: Lies die Fehlermeldung und behebe das Problem direkt.

---
