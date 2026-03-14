# acknowledgements.py
"""Intelligente Bestaetigungsnachrichten fuer eingehende Prompts.
Primaer: Haiku generiert passgenaue Zusammenfassung via Claude CLI.
Fallback: 150 zufaellige Nachrichten.
"""

import asyncio
import logging
import os
import random

logger = logging.getLogger(__name__)

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
ACK_TIMEOUT = float(os.getenv("ACK_TIMEOUT", "4.0"))

FALLBACK_MESSAGES = [
    "🚀 Angekommen! Claude denkt nach...",
    "📨 Erhalten! Bin dran...",
    "⚡ Got it! Arbeite daran...",
    "🧠 Nachricht angekommen — Claude gruebelt...",
    "🎯 Empfangen! Los geht's...",
    "💡 Alles klar, bin dabei...",
    "🔥 Auf dem Weg! Claude legt los...",
    "✨ Deine Nachricht ist da — wird verarbeitet...",
    "🤖 Roger that! Claude ist dran...",
    "📡 Signal empfangen! Verarbeitung laeuft...",
    "🏃 Bin schon unterwegs...",
    "⏳ Angekommen — Claude arbeitet...",
    "🎬 Action! Claude startet...",
    "🧩 Puzzle empfangen — wird geloest...",
    "🛠️ Auftrag erhalten! Werkzeuge werden ausgepackt...",
    "🌟 Nachricht gelandet — Claude liefert...",
    "📋 Notiert! Wird bearbeitet...",
    "🔧 Eingegangen! Claude schraubt daran...",
    "💻 Code-Modus aktiviert...",
    "🎪 Vorhang auf! Claude performt...",
    "🚂 Zug faehrt ab — Antwort kommt...",
    "🌊 Nachricht gesurft — Claude taucht ein...",
    "🎸 Rock'n'Roll! Bin dran...",
    "🏗️ Baustelle eroeffnet — Claude baut...",
    "🔬 Analysiere deine Anfrage...",
    "🎯 Ziel erfasst! Claude feuert...",
    "🧪 Experiment startet...",
    "📦 Paket empfangen — wird ausgepackt...",
    "🗺️ Route berechnet — Claude navigiert...",
    "🎨 Pinsel gezueckt — Claude malt...",
    "🏄 Auf der Welle! Antwort kommt...",
    "⚙️ Zahnraeder drehen sich...",
    "🔮 Kristallkugel wird befragt...",
    "🎲 Wuerfel gefallen — Claude rechnet...",
    "🧲 Angezogen! Claude ist magnetisiert...",
    "📝 Stift gespitzt — Claude schreibt...",
    "🔭 Teleskop ausgerichtet — Claude sucht...",
    "🎵 Die Melodie spielt — Claude komponiert...",
    "🏋️ Schwere Frage? Kein Problem...",
    "🌈 Farbenfroh empfangen! Antwort kommt bunt...",
    "🦾 Arme hochgekrempelt — los geht's...",
    "📡 Auf Empfang! Verarbeitung startet...",
    "🎪 Manege frei fuer Claude...",
    "🧭 Kompass ausgerichtet — Claude findet den Weg...",
    "⚡ Blitzschnell empfangen! Antwort braucht einen Moment...",
    "🌍 Weltklasse-Anfrage! Claude gibt sein Bestes...",
    "🏰 Festung erhalten — Claude verteidigt die Antwort...",
    "🎤 Mikro an — Claude spricht gleich...",
    "🔋 Aufgeladen! Claude laeuft auf Hochtouren...",
    "🧬 DNA der Frage wird entschluesselt...",
    "🛸 Transmission empfangen! Claude dekodiert...",
    "🎭 Buehne bereitet — Antwort wird inszeniert...",
    "🏹 Pfeil gespannt — Claude zielt auf die Antwort...",
    "🎻 Saiten gestimmt — Claude spielt gleich...",
    "🧊 Cool, hab's! Antwort wird aufgetaut...",
    "🔥 Feuer frei! Claude zuendet...",
    "🦅 Adlerauge hat's erfasst...",
    "🎢 Achterbahn startet — halt dich fest...",
    "📚 Buch aufgeschlagen — Claude recherchiert...",
    "🔑 Schluessel erhalten — Claude schliesst auf...",
    "🧰 Werkzeugkasten geoeffnet...",
    "🎳 Strike! Nachricht im Ziel...",
    "🏊 Eintauchen in deine Frage...",
    "🌋 Vulkan erwacht — Claude brodelt...",
    "🛡️ Schild bereit — Claude kaempft fuer die Antwort...",
    "🎯 Bullseye! Nachricht angekommen...",
    "🧙 Zauberstab gezueckt...",
    "🏎️ Motor laeuft! Claude gibt Gas...",
    "🌪️ Wirbelsturm der Gedanken startet...",
    "🦸 Superheld Claude aktiviert...",
    "🎰 Jackpot! Deine Nachricht ist da...",
    "🔍 Lupe raus — Claude untersucht...",
    "🏆 Champion-Anfrage! Claude kaempft...",
    "🧁 Suesse Nachricht! Claude backt die Antwort...",
    "🎺 Fanfare! Claude tritt an...",
    "🌠 Sternschnuppe gefangen — Wunsch wird erfuellt...",
    "🧗 Klettere an deiner Frage hoch...",
    "🎪 Zirkus startet — Claude jongliert...",
    "🔨 Hammer bereit — Claude schmiedet die Antwort...",
    "🎣 Angebissen! Claude zieht die Antwort raus...",
    "🏄‍♂️ Surfbrett bereit — Claude reitet die Welle...",
    "🦊 Schlau empfangen! Claude ist fuchsig dran...",
    "💎 Diamant-Anfrage! Wird geschliffen...",
    "🎮 Game on! Claude spielt...",
    "🧶 Faden aufgenommen — Claude strickt die Antwort...",
    "🔦 Taschenlampe an — Claude leuchtet den Weg...",
    "🎷 Jazz! Claude improvisiert...",
    "🏗️ Grundstein gelegt — Antwort wird gebaut...",
    "🧲 Magnetisch angezogen! Claude haftet dran...",
    "🌻 Sonnenblume dreht sich — Claude folgt der Frage...",
    "🎩 Hut ab! Claude zaubert gleich...",
    "🦁 Loewe bruellt — Claude gibt alles...",
    "🏺 Amphore geoeffnet — Weisheit fliesst...",
    "🎼 Partitur gelesen — Claude dirigiert...",
    "🧪 Labor offen — Claude experimentiert...",
    "🔐 Code geknackt — Claude entschluesselt...",
    "🎠 Karussell dreht sich — Antwort kommt rum...",
    "🌵 Auch in der Wueste liefert Claude...",
    "🦉 Weise Eule Claude denkt nach...",
    "🎆 Feuerwerk wird vorbereitet...",
    "🧩 Puzzleteil gefunden — wird eingesetzt...",
    "🏰 Turm bestiegen — Ueberblick wird verschafft...",
    "🎿 Ab auf die Piste! Claude carved die Antwort...",
    "🌊 Tieftaucher Claude geht unter...",
    "🦜 Papagei hat's gehoert — Claude plappert gleich zurueck...",
    "📬 Post ist da! Claude oeffnet den Umschlag...",
    "🎪 Trommelwirbel... Antwort kommt!",
    "🧮 Abakus klackert — Claude rechnet...",
    "🔩 Schraube angezogen — Claude dreht...",
    "🌙 Mondschein-Anfrage empfangen...",
    "🏋️‍♀️ Gewichte stemmen fuer die perfekte Antwort...",
    "🎲 Die Wuerfel rollen...",
    "🧵 Roter Faden gefunden — Claude folgt...",
    "🎻 Virtuose Claude stimmt ein...",
    "🔬 Mikroskop scharf gestellt...",
    "🌪️ Gedankentornado formt sich...",
    "🦈 Claude taucht in die Tiefe...",
    "🎭 Maske auf — Claude schlupft in die Rolle...",
    "🧊 Eiskalt empfangen — Claude waermt die Antwort auf...",
    "🎯 Pfeil trifft! Claude rennt zum Ziel...",
    "🦋 Schmetterling gelandet — Claude entfaltet...",
    "🏺 Altes Wissen wird konsultiert...",
    "🎸 Power-Chord! Claude rockt die Antwort...",
    "🔭 Horizont abgesucht — Claude sieht die Loesung...",
    "🧃 Saft gepresst — Claude extrahiert die Essenz...",
    "🎪 Akrobatik-Einlage — Claude turnt zur Antwort...",
    "🌺 Bluete oeffnet sich — Antwort erblueht...",
    "🦝 Waschbaer Claude waescht die Fakten rein...",
    "🏹 Bogenschuetze Claude hat gespannt...",
    "🧗‍♂️ Gipfelsturm startet...",
    "🎵 Playlist laeuft — Claude groovt zur Antwort...",
    "🔧 Feintuning laeuft...",
    "🌅 Sonnenaufgang — Claude erleuchtet gleich...",
    "🦾 Turbo aktiviert!",
    "🧠 Synapsen feuern...",
    "📖 Kapitel wird aufgeschlagen...",
    "🎬 Klappe, die erste — Claude dreht...",
    "🔋 100% geladen — Claude startet durch...",
    "🌟 Sternstunde! Claude glaenzt gleich...",
    "🏄 Wellenreiter Claude paddelt los...",
    "🧪 Reagenzglas brodelt...",
    "🎯 Laser-Fokus aktiviert...",
    "🦅 Im Sturzflug auf die Antwort...",
    "🎩 Abrakadabra — Antwort erscheint gleich...",
    "🏎️ Pole Position! Claude rast los...",
    "🌈 Am Ende des Regenbogens wartet die Antwort...",
    "💫 Kosmische Anfrage! Claude channelt das Universum...",
    "🧲 Anziehungskraft wirkt — Antwort naehert sich...",
]


def _get_fallback() -> str:
    return random.choice(FALLBACK_MESSAGES)


async def generate_acknowledgement(user_prompt: str) -> str:
    """Generiert via Haiku eine passgenaue Bestaetigung. Fallback auf Zufallsnachricht."""
    haiku_prompt = (
        "Der User hat folgende Nachricht an Claude Code geschickt:\n"
        f'"{user_prompt[:300]}"\n\n'
        "Antworte mit GENAU einem kurzen Satz (max 15 Worte) mit passendem Emoji vorne. "
        "Fasse zusammen was verstanden wurde und was jetzt passiert. "
        "Sei locker, kreativ, abwechslungsreich. Kein Markdown. Nur der Satz, nichts sonst."
    )
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                CLAUDE_BIN, "-p", haiku_prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--max-turns", "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=ACK_TIMEOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=ACK_TIMEOUT)
        result = stdout.decode("utf-8", errors="replace").strip()
        if result and len(result) < 200:
            return result
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Haiku-Acknowledgement fehlgeschlagen: %s", e)
    return _get_fallback()
