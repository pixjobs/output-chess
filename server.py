from flask import Flask, request, jsonify
from flask_cors import CORS
import chess
import chess.engine
import os
import random
import threading
import atexit

app = Flask(__name__, static_folder="frontend/dist")
CORS(app)  # allow cross-origin requests (Vercel frontend → Cloud Run backend)

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", os.path.abspath("./stockfish"))


class EngineWrapper:
    """Thin wrapper around a UCI engine with lifecycle management."""

    def __init__(self, path: str, name: str):
        self.path = path
        self.name = name
        self._engine = None
        self._lock = threading.Lock()

    def start(self):
        if self._engine:
            return
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path)

    def play(self, board: chess.Board, limit, options: dict | None = None) -> chess.engine.PlayResult:
        with self._lock:
            if options:
                self._engine.configure(options)
            return self._engine.play(board, limit)

    def shutdown(self):
        if self._engine:
            self._engine.quit()
            self._engine = None


# ---------------------------------------------------------------------------
# RandomBot — pure-Python engine that plays legal random moves.
# Perfect for ~150 elo level.
# ---------------------------------------------------------------------------


class RandomBot:
    """Pure-Python engine that plays random legal moves.
    No UCI subprocess needed — just plays a random legal move.
    """

    def __init__(self, name: str):
        self.name = name

    def start(self):
        pass  # no subprocess to start

    def play(self, board: chess.Board, limit, options: dict | None = None) -> chess.engine.PlayResult:
        moves = list(board.legal_moves)
        if not moves:
            raise chess.EngineError("No legal moves")
        return chess.engine.PlayResult(random.choice(moves), None, info=None, draw_offered=False)

    def shutdown(self):
        pass


# Registry
ENGINE_REGISTRY: dict[str, dict] = {
    "stockfish": {
        "name": "Stockfish",
        "path": STOCKFISH_PATH,
        "skill_range": (0, 20),
        "min_elo": 400,
        "max_elo": 3500,
    },
    # Stockfish with a 20 ms time cap — forces very shallow search (~500–900 ELO)
    "stockfish_blitz": {
        "name": "Stockfish Blitz",
        "path": STOCKFISH_PATH,
        "skill_range": (0, 10),
        "min_elo": 300,
        "max_elo": 900,
        "time_limit": 0.02,
    },
    "random": {
        "name": "RandomBot",
        "skill_range": (0, 0),
        "min_elo": 100,
        "max_elo": 300,
        "random_bot": True,
    },
}


class EnginePool:
    """Lazy pool: one engine per key, reused for both colors."""

    def __init__(self):
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def get(self, engine_key: str) -> object:
        with self._lock:
            if engine_key not in self._cache:
                info = ENGINE_REGISTRY[engine_key]
                if info.get("random_bot"):
                    wrapper = RandomBot(info["name"])
                else:
                    wrapper = EngineWrapper(info["path"], info["name"])
                wrapper.start()
                self._cache[engine_key] = wrapper
            return self._cache[engine_key]

    def shutdown_all(self):
        with self._lock:
            for w in self._cache.values():
                w.shutdown()
            self._cache.clear()


pool = EnginePool()


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------


class GameState:
    def __init__(self):
        self.mode = "bot_vs_bot"
        self.white_engine = "stockfish"
        self.black_engine = "stockfish"
        self.white_skill = 10
        self.black_skill = 5
        self.player_color = chess.BLACK
        self.board = chess.Board()
        self.moves: list[dict] = []

    def reset(self, mode=None):
        self.board = chess.Board()
        self.moves = []
        if mode:
            self.mode = mode
        if self.mode == "player_vs_bot":
            self.black_skill = 5
        else:
            self.white_skill = 10
            self.black_skill = 5

    def skill_options(self, engine_key: str, skill: int) -> dict:
        info = ENGINE_REGISTRY.get(engine_key, {})
        sr = info.get("skill_range", (0, 20))
        return {"Skill Level": max(sr[0], min(sr[1], skill))}


state = GameState()


def _is_human_turn() -> bool:
    if state.mode != "player_vs_bot":
        return False
    if state.player_color == chess.WHITE:
        return state.board.turn == chess.WHITE
    return state.board.turn == chess.BLACK

def _do_bot_move() -> dict:
    """Play one bot move. Caller must ensure it's actually the bot's turn."""
    is_white_turn = state.board.turn == chess.WHITE
    engine_key = state.white_engine if is_white_turn else state.black_engine
    bot_info = ENGINE_REGISTRY.get(engine_key, {})
    bot = pool.get(engine_key)
    if bot_info.get("random_bot"):
        result = bot.play(state.board, chess.engine.Limit(time=0.3))
    else:
        skill = state.white_skill if is_white_turn else state.black_skill
        opts = state.skill_options(engine_key, skill)
        time_lim = bot_info.get("time_limit", 0.5)
        result = bot.play(state.board, chess.engine.Limit(time=time_lim), options=opts)
    san = state.board.san(result.move)
    state.board.push(result.move)
    state.moves.append({
        "san": san,
        "from": result.move.uci()[:2],
        "to": result.move.uci()[2:],
        "color": "white" if is_white_turn else "black",
    })
    return {
        "move": result.move.uci(),
        "from": result.move.uci()[:2],
        "to": result.move.uci()[2:],
        "fen": state.board.fen(),
        "game_over": state.board.is_game_over(),
        "result": state.board.result() if state.board.is_game_over() else "",
        "turn": "white" if state.board.turn == chess.WHITE else "black",
        "engine": bot_info.get("name", engine_key),
        "in_check": state.board.is_check(),
        "san": san,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    engines = []
    for key, info in ENGINE_REGISTRY.items():
        engines.append({
            "id": key,
            "name": info["name"],
            "min_elo": info["min_elo"],
            "max_elo": info["max_elo"],
            "skill_range": info["skill_range"],
        })

    return jsonify({
        "engines": engines,
        "mode": state.mode,
        "white_engine": state.white_engine,
        "black_engine": state.black_engine,
        "white_skill": state.white_skill,
        "black_skill": state.black_skill,
        "player_color": "white" if state.player_color == chess.WHITE else "black",
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    data = request.json or {}

    if "mode" in data:
        state.mode = data["mode"]
    if "white_engine" in data:
        state.white_engine = data["white_engine"]
    if "black_engine" in data:
        state.black_engine = data["black_engine"]
    if "white_skill" in data:
        state.white_skill = data["white_skill"]
    if "black_skill" in data:
        state.black_skill = data["black_skill"]
    if "player_color" in data:
        state.player_color = chess.WHITE if data["player_color"] == "white" else chess.BLACK

    state.reset(mode=state.mode)
    return jsonify({"status": "ok"})


@app.route("/move", methods=["POST"])
def get_move():
    if state.board.is_game_over():
        return jsonify({"game_over": True, "result": state.board.result()})

    if _is_human_turn():
        is_white_turn = state.board.turn == chess.WHITE
        return jsonify({
            "human_turn": True,
            "fen": state.board.fen(),
            "turn": "white" if is_white_turn else "black",
            "in_check": state.board.is_check(),
        })

    try:
        return jsonify(_do_bot_move())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/player-move", methods=["POST"])
def player_move():
    data = request.json or {}
    move_uci = data.get("move", "")
    if not move_uci or len(move_uci) < 4:
        return jsonify({"error": "Invalid move"}), 400

    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        return jsonify({"error": "Not a valid UCI move"}), 400

    if state.board.is_game_over():
        return jsonify({"error": "Game is over", "game_over": True, "result": state.board.result()})

    legal_moves = [m.uci() for m in state.board.legal_moves]
    if move_uci not in legal_moves:
        return jsonify({"error": f"Move {move_uci} is not legal"}), 400

    san = state.board.san(move)
    state.board.push(move)
    state.moves.append({
        "san": san,
        "from": move.uci()[:2],
        "to": move.uci()[2:],
        "color": "white" if state.board.turn == chess.WHITE else "black",
    })
    fen = state.board.fen()
    game_over = state.board.is_game_over()
    if game_over:
        return jsonify({
            "move": move_uci,
            "san": san,
            "fen": fen,
            "game_over": True,
            "result": state.board.result(),
            "turn": "white" if state.board.turn == chess.WHITE else "black",
            "in_check": state.board.is_check(),
        })
    # Bot responds
    bot_resp = _do_bot_move()
    return jsonify({
        "move": move_uci,
        "san": san,
        "bot_move": bot_resp["move"],
        "bot_san": bot_resp["san"],
        "fen": bot_resp["fen"],
        "game_over": bot_resp["game_over"],
        "result": bot_resp["result"],
        "turn": bot_resp["turn"],
        "engine": bot_resp["engine"],
        "in_check": bot_resp["in_check"],
    })


@app.route("/api/moves")
def get_moves():
    """Return grouped move history."""
    grouped = []
    move_num = 1
    i = 0
    while i < len(state.moves):
        entry = state.moves[i]
        white_entry = {"san": entry["san"], "from": entry["from"], "to": entry["to"]}
        black_entry = None
        if i + 1 < len(state.moves) and state.moves[i + 1]["color"] == "black":
            black_entry = {"san": state.moves[i + 1]["san"],
                           "from": state.moves[i + 1]["from"],
                           "to": state.moves[i + 1]["to"]}
            i += 1
        grouped.append({"moveNumber": move_num, "white": white_entry, "black": black_entry})
        move_num += 1
        i += 1
    return jsonify(grouped)

@app.route("/status")
def status():
    return jsonify({
        "fen": state.board.fen(),
        "game_over": state.board.is_game_over(),
        "result": state.board.result() if state.board.is_game_over() else "",
        "mode": state.mode,
        "turn": "white" if state.board.turn == chess.WHITE else "black",
        "in_check": state.board.is_check(),
    })


@app.route("/legal-moves/<sq>")
def legal_moves(sq):
    if len(sq) != 2 or sq[0] < 'a' or sq[0] > 'h' or sq[1] < '1' or sq[1] > '8':
        return jsonify({"error": "Invalid square"}), 400
    moves = [m.uci() for m in state.board.legal_moves if m.uci()[:2] == sq]
    return jsonify({"moves": moves})


@app.route("/reset")
def reset():
    state.reset(mode=state.mode)
    return jsonify({"status": "ok"})


@app.route("/<path:path>")
def catch_all(path):
    """SPA fallback: serve index.html for any non-API, non-static route."""
    if path.startswith("api/") or path.startswith("move") or path == "status":
        return jsonify({"error": "Not found"}), 404
    if path.startswith("assets/") or path == "favicon.svg" or path == "icons.svg":
        return app.send_static_file(path)
    return app.send_static_file("index.html")


@atexit.register
def _cleanup():
    pool.shutdown_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5500))
    print(f"Server at http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
