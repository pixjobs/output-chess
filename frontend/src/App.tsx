import { useEffect, useRef, useState } from 'react';
import {
  ChessboardProvider,
  Chessboard,
  defaultPieces,
  fenStringToPositionObject,
} from 'react-chessboard';
import type { ChessboardOptions, PositionDataType } from 'react-chessboard';
import './index.css';

// ── Types ──────────────────────────────────────────────────────────────────

interface Engine {
  id: string;
  name: string;
  min_elo: number;
  max_elo: number;
  skill_range: [number, number];
}

interface ServerConfig {
  engines: Engine[];
  mode: 'bot_vs_bot' | 'player_vs_bot';
  white_engine: string;
  black_engine: string;
  white_skill: number;
  black_skill: number;
  player_color: 'white' | 'black';
}

// When the frontend is deployed separately (Vercel) set VITE_API_BASE to the backend URL.
// In single-container deployments (Cloud Run / local) leave it unset for relative paths.
const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

// ── Constants ──────────────────────────────────────────────────────────────

const ENGINE_ICONS: Record<string, string> = {
  stockfish: '♞',
  stockfish_blitz: '⚡',
  random: '🎲',
};

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

const PROMOTION_CHARS = ['q', 'r', 'b', 'n'] as const;
const PROMOTION_DISPLAY: Record<string, string> = { q: '♕', r: '♖', b: '♗', n: '♘' };

const ELO_MAP: Record<number, number> = {
  0: 400, 1: 500, 2: 580, 3: 680, 4: 780, 5: 880, 6: 980, 7: 1080,
  8: 1180, 9: 1280, 10: 1400, 11: 1520, 12: 1650, 13: 1780, 14: 1900,
  15: 2050, 16: 2180, 17: 2300, 18: 2500, 19: 2800, 20: 3200,
};

const PIECE_VALUES: Record<string, number> = { P: 1, N: 3, B: 3, R: 5, Q: 9 };
const STARTING_COUNT: Record<string, number> = { P: 8, N: 2, B: 2, R: 2, Q: 1 };
const PIECE_SYMBOLS: Record<string, string> = {
  P: '♙', N: '♘', B: '♗', R: '♖', Q: '♕',
  p: '♟', n: '♞', b: '♝', r: '♜', q: '♛',
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fenToPos(fen: string): PositionDataType {
  return fenStringToPositionObject(fen, 8, 8);
}

function isOwnPiece(pieceType: string, color: 'white' | 'black') {
  return color === 'white' ? pieceType[0] === 'w' : pieceType[0] === 'b';
}

function pieceOnSquare(fen: string, square: string): string | null {
  const file = square.charCodeAt(0) - 97;
  const rank = 8 - parseInt(square[1]);
  const ranks = fen.split(' ')[0].split('/');
  let col = 0;
  for (const ch of ranks[rank]) {
    if (ch >= '1' && ch <= '8') { col += parseInt(ch); continue; }
    if (col === file) return ch;
    col++;
  }
  return null;
}

function findKingSquare(fen: string, color: 'white' | 'black'): string | null {
  const target = color === 'white' ? 'K' : 'k';
  const ranks = fen.split(' ')[0].split('/');
  for (let rank = 0; rank < 8; rank++) {
    let file = 0;
    for (const ch of ranks[rank]) {
      if (ch >= '1' && ch <= '8') { file += parseInt(ch); continue; }
      if (ch === target) return `${String.fromCharCode(97 + file)}${8 - rank}`;
      file++;
    }
  }
  return null;
}

function computeMaterial(fen: string) {
  const counts: Record<string, { w: number; b: number }> = {
    P: { w: 0, b: 0 }, N: { w: 0, b: 0 }, B: { w: 0, b: 0 },
    R: { w: 0, b: 0 }, Q: { w: 0, b: 0 },
  };
  for (const ch of fen.split(' ')[0]) {
    const up = ch.toUpperCase();
    if (up in counts) counts[up][ch === up ? 'w' : 'b']++;
  }
  const advantage = Object.entries(PIECE_VALUES).reduce(
    (s, [t, v]) => s + (counts[t].w - counts[t].b) * v, 0,
  );
  const blackCaptured: string[] = [];
  const whiteCaptured: string[] = [];
  for (const t of ['Q', 'R', 'B', 'N', 'P'] as const) {
    for (let i = 0; i < STARTING_COUNT[t] - counts[t].w; i++) blackCaptured.push(PIECE_SYMBOLS[t]);
    for (let i = 0; i < STARTING_COUNT[t] - counts[t].b; i++) whiteCaptured.push(PIECE_SYMBOLS[t.toLowerCase()]);
  }
  return { advantage, whiteCaptured, blackCaptured };
}

function groupMoves(moves: { san: string }[]): { n: number; w: string; b: string }[] {
  const out: { n: number; w: string; b: string }[] = [];
  for (let i = 0; i < moves.length; i += 2)
    out.push({ n: Math.floor(i / 2) + 1, w: moves[i]?.san ?? '', b: moves[i + 1]?.san ?? '' });
  return out;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function App() {
  const [config, setConfig] = useState<ServerConfig | null>(null);
  const configRef = useRef<ServerConfig | null>(null);
  configRef.current = config;

  const [position, setPosition] = useState<PositionDataType>(fenToPos(START_FEN));
  const [currentFen, setCurrentFen] = useState(START_FEN);
  const [gameOver, setGameOver] = useState(false);
  const [gameResult, setGameResult] = useState('');
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  playingRef.current = playing;

  const [selectedSq, setSelectedSq] = useState<string | null>(null);
  const [promoPending, setPromoPending] = useState<{ from: string; to: string } | null>(null);
  const [whiteTurn, setWhiteTurn] = useState(true);
  const [moveInterval, setMoveInterval] = useState(600);
  const [moves, setMoves] = useState<{ san: string; color: 'white' | 'black' }[]>([]);
  const [statusText, setStatusText] = useState('READY');
  const [inCheck, setInCheck] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const movesEndRef = useRef<HTMLDivElement | null>(null);

  const isHumanTurn =
    config?.mode === 'player_vs_bot' &&
    config?.player_color === (whiteTurn ? 'white' : 'black');

  useEffect(() => { movesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [moves]);
  useEffect(() => { fetch(`${API}/api/config`).then((r) => r.json()).then(setConfig); }, []);

  // ── API ────────────────────────────────────────────────────────────────

  async function pushConfig(cfg: ServerConfig) {
    await fetch(`${API}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: cfg.mode, white_engine: cfg.white_engine, black_engine: cfg.black_engine,
        white_skill: cfg.white_skill, black_skill: cfg.black_skill,
        player_color: cfg.player_color,
      }),
    });
  }

  // ── Config mutations ───────────────────────────────────────────────────

  function setMode(mode: 'bot_vs_bot' | 'player_vs_bot') {
    setConfig((prev) => {
      if (!prev) return prev;
      const next = { ...prev, mode, white_skill: mode === 'bot_vs_bot' ? 10 : prev.white_skill, black_skill: 5 };
      pushConfig(next);
      return next;
    });
    doReset();
  }

  function setEngine(side: 'white' | 'black', id: string) {
    if (!config) return;
    const next = { ...config, [side === 'white' ? 'white_engine' : 'black_engine']: id };
    setConfig(next); pushConfig(next); doReset();
  }

  function setSkill(side: 'white' | 'black', val: number) {
    if (!config) return;
    const next = { ...config, [side === 'white' ? 'white_skill' : 'black_skill']: val };
    setConfig(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => pushConfig(next), 300);
  }

  function setPlayerColor(color: 'white' | 'black') {
    if (!config) return;
    const next = { ...config, player_color: color };
    setConfig(next); pushConfig(next); doReset();
  }

  // ── Game control ───────────────────────────────────────────────────────

  function doReset() {
    setPlaying(false); setGameOver(false); setGameResult('');
    setSelectedSq(null); setMoves([]); setInCheck(false);
    setPosition(fenToPos(START_FEN)); setCurrentFen(START_FEN);
    setWhiteTurn(true); setStatusText('READY');
    fetch(`${API}/reset`);
  }

  async function startGame() {
    const cfg = configRef.current;
    if (!cfg) return;
    setPlaying(true); setGameOver(false); setGameResult('');
    setStatusText('COMPUTING…');
    await pushConfig(cfg);
    botLoop();
  }

  async function botLoop() {
    if (!playingRef.current) return;
    try {
      const r = await fetch(`${API}/move`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const d = await r.json();
      if (d.error) { setStatusText(`ERR: ${d.error}`); setPlaying(false); return; }
      if (d.human_turn) { setStatusText('AWAITING INPUT'); setPlaying(false); return; }
      applyFen(d.fen);
      setInCheck(d.in_check ?? false);
      if (d.san) appendMove(d.san, d.turn === 'white' ? 'white' : 'black');
      setStatusText(d.in_check ? '⚡ CHECK' : d.turn === 'white' ? 'WHITE TO MOVE' : 'BLACK TO MOVE');
      if (d.game_over) { endGame(d.result); return; }
      setTimeout(botLoop, moveInterval);
    } catch { setStatusText('CONNECTION LOST'); setPlaying(false); }
  }

  async function sendMove(from: string, to: string, promo?: string) {
    setSelectedSq(null);
    const cfg = configRef.current!;
    try {
      const r = await fetch(`${API}/player-move`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ move: from + to + (promo ?? '') }),
      });
      const d = await r.json();
      if (d.error) { setStatusText(`ILLEGAL MOVE`); return; }
      applyFen(d.fen);
      setInCheck(d.in_check ?? false);
      if (d.san) appendMove(d.san, cfg.player_color);
      if (d.bot_san) appendMove(d.bot_san, cfg.player_color === 'white' ? 'black' : 'white');
      if (d.game_over) { endGame(d.result); return; }
      setStatusText(d.in_check ? '⚡ CHECK' : 'AWAITING INPUT');
    } catch (e) { setStatusText(`ERR: ${(e as Error).message}`); }
  }

  function applyFen(fen: string) {
    setCurrentFen(fen); setPosition(fenToPos(fen));
    setWhiteTurn(fen.split(' ')[1] === 'w');
  }

  function appendMove(san: string, color: 'white' | 'black') {
    setMoves((prev) => [...prev, { san, color }]);
  }

  function endGame(result: string) {
    setGameOver(true); setGameResult(result); setPlaying(false); setStatusText('GAME OVER');
  }

  // ── Event handlers ────────────────────────────────────────────────────

  function onPieceClick({ piece, square }: { piece: { pieceType: string } | null; square: string | null }) {
    if (!config || !isHumanTurn || gameOver || config.mode !== 'player_vs_bot') return;
    if (piece && isOwnPiece(piece.pieceType, config.player_color)) setSelectedSq(square);
    else setSelectedSq(null);
  }

  function onSquareClick({ square }: { square: string; piece: { pieceType: string } | null }) {
    if (!config || !isHumanTurn || gameOver || config.mode !== 'player_vs_bot') return;
    if (selectedSq === square) { setSelectedSq(null); return; }
    if (selectedSq) {
      const movingPiece = pieceOnSquare(currentFen, selectedSq);
      const isPawn = movingPiece === 'P' || movingPiece === 'p';
      if (isPawn && square[1] === (config.player_color === 'white' ? '8' : '1')) {
        setPromoPending({ from: selectedSq, to: square }); return;
      }
      sendMove(selectedSq, square);
    }
  }

  function handlePromotion(p: string) {
    if (!promoPending) return;
    sendMove(promoPending.from, promoPending.to, p);
    setPromoPending(null);
  }

  // ── Render ─────────────────────────────────────────────────────────────

  if (!config) {
    return (
      <div className="boot-screen">
        <div className="boot-knight">♞</div>
        <div className="boot-logo">OUTPUT<span className="logo-sep">//</span>CHESS</div>
        <div className="boot-status">INITIALISING ENGINES…</div>
      </div>
    );
  }

  const material = computeMaterial(currentFen);
  const grouped = groupMoves(moves);

  const checkSq = inCheck ? findKingSquare(currentFen, whiteTurn ? 'white' : 'black') : null;
  const squareStyles: Record<string, React.CSSProperties> = {};
  if (checkSq) squareStyles[checkSq] = { backgroundColor: 'rgba(220,53,69,0.5)' };
  if (selectedSq) squareStyles[selectedSq] = { backgroundColor: 'rgba(56,189,248,0.45)' };

  const boardOpts: ChessboardOptions = {
    position,
    boardOrientation: config.mode === 'player_vs_bot' ? config.player_color : 'white',
    allowDragOffBoard: false,
    animationDurationInMs: 160,
    showNotation: true,
    pieces: defaultPieces,
    onPieceClick,
    onSquareClick,
    squareStyles,
    darkSquareStyle: { backgroundColor: '#3d5a7a' },
    lightSquareStyle: { backgroundColor: '#8aaec8' },
    boardStyle: { borderRadius: '2px', boxShadow: '0 0 0 1px rgba(56,189,248,0.2), 0 8px 48px rgba(0,0,0,0.7)' },
  };

  const bottomSide: 'white' | 'black' = config.mode === 'player_vs_bot' ? config.player_color : 'white';
  const topSide: 'white' | 'black' = bottomSide === 'white' ? 'black' : 'white';

  const resultLabel =
    gameResult === '1-0' ? 'WHITE WINS' :
    gameResult === '0-1' ? 'BLACK WINS' : 'DRAW';
  const resultIcon =
    gameResult === '1-0' ? '♔' :
    gameResult === '0-1' ? '♚' : '⚖';
  const resultClass =
    gameResult === '1-0' ? 'result-white' :
    gameResult === '0-1' ? 'result-black' : 'result-draw';

  function PlayerStrip({ side }: { side: 'white' | 'black' }) {
    const skill = side === 'white' ? config!.white_skill : config!.black_skill;
    const engineId = side === 'white' ? config!.white_engine : config!.black_engine;
    const isPlayer = config!.mode === 'player_vs_bot' && config!.player_color === side;
    const captured = side === 'black' ? material.blackCaptured : material.whiteCaptured;
    const adv = side === 'white' ? material.advantage : -material.advantage;
    const isActive = (side === 'white') === whiteTurn;
    const kingIcon = side === 'white' ? '♔' : '♚';

    return (
      <div className={`player-strip ${isActive && !gameOver ? 'active-turn' : ''}`}>
        <div className="strip-left">
          <span className={`king-icon king-${side}`}>{kingIcon}</span>
          <div className="strip-engine">
            {isPlayer ? (
              <span className="strip-name human">♟ YOU</span>
            ) : (
              <select className="engine-select" value={engineId}
                onChange={(e) => setEngine(side, e.target.value)}>
                {config!.engines.map((e) => (
                  <option key={e.id} value={e.id}>
                    {ENGINE_ICONS[e.id] ?? '♟'} {e.name.toUpperCase()}
                  </option>
                ))}
              </select>
            )}
            {!isPlayer && <span className="elo-tag">{ELO_MAP[skill]} ELO</span>}
          </div>
        </div>
        <div className="strip-right">
          {!isPlayer && (
            <div className="skill-row">
              <span className="skill-val">SL{skill.toString().padStart(2, '0')}</span>
              <input type="range" min={0} max={20} value={skill} className="skill-track"
                onInput={(e: React.SyntheticEvent<HTMLInputElement>) => setSkill(side, parseInt(e.currentTarget.value))} />
            </div>
          )}
          <div className="captured-row">
            {captured.map((s, i) => <span key={i}>{s}</span>)}
            {adv > 0 && <span className="adv-badge">+{adv}</span>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <header className="app-header">
        <div className="logo">
          <span className="logo-knight">♞</span> <span className="logo-wordmark">OUTPUT<span className="logo-sep">//</span>CHESS</span>
        </div>
        <nav className="header-nav">
          {config.mode === 'player_vs_bot' && (
            <div className="play-as-group">
              <span className="nav-label">PLAY AS</span>
              <button className={`side-btn ${config.player_color === 'white' ? 'active' : ''}`}
                onClick={() => setPlayerColor('white')}>WHITE</button>
              <button className={`side-btn ${config.player_color === 'black' ? 'active' : ''}`}
                onClick={() => setPlayerColor('black')}>BLACK</button>
            </div>
          )}
          <div className="mode-tabs">
            <button className={`mode-tab ${config.mode === 'bot_vs_bot' ? 'active' : ''}`}
              onClick={() => setMode('bot_vs_bot')}>⚔ BOT VS BOT</button>
            <button className={`mode-tab ${config.mode === 'player_vs_bot' ? 'active' : ''}`}
              onClick={() => setMode('player_vs_bot')}>♟ PLAY VS BOT</button>
          </div>
        </nav>
      </header>

      <div className="main-layout">
        <section className="board-column">
          <PlayerStrip side={topSide} />

          <div className="board-wrapper">
            <ChessboardProvider options={boardOpts}>
              <Chessboard />
            </ChessboardProvider>
            {gameOver && (
              <div className="game-over-overlay">
                <div className={`game-over-panel ${resultClass}`}>
                  <div className="game-over-icon-big">{resultIcon}</div>
                  <div className="game-over-result">{resultLabel}</div>
                  <div className="game-over-sub">{gameResult === '1/2-1/2' ? 'DRAW' : 'CHECKMATE!'}</div>
                  <button className="action-btn primary" onClick={doReset}>♟ NEW GAME</button>
                </div>
              </div>
            )}
          </div>

          <PlayerStrip side={bottomSide} />

          <div className="board-footer">
            <div className={`status-readout ${playing ? 'active' : ''}`}>{statusText}</div>
            <div className="controls-row">
              <button className={`action-btn primary ${playing ? 'running' : ''}`}
                onClick={startGame} disabled={playing || gameOver}>
                {playing ? '⏸ RUNNING' : '▶ EXECUTE'}
              </button>
              <button className="action-btn" onClick={doReset}>↺ RESET</button>
              <label className="clock-control">
                <span className="nav-label">CLOCK</span>
                <input type="range" min={50} max={2000} value={moveInterval}
                  onChange={(e) => setMoveInterval(parseInt(e.target.value))} />
                <span className="clock-val">{(moveInterval / 1000).toFixed(1)}s</span>
              </label>
            </div>
          </div>
        </section>

        <aside className="sidebar">
          <div className="panel move-log-panel">
            <div className="panel-header">♟ MOVE LOG</div>
            {grouped.length === 0 ? (
              <div className="log-empty">— NO MOVES YET —</div>
            ) : (
              <div className="log-list">
                {grouped.map((g) => (
                  <div key={g.n} className="log-row">
                    <span className="log-n">{g.n.toString().padStart(2, '0')}.</span>
                    <span className="log-w">{g.w}</span>
                    {g.b && <span className="log-b">{g.b}</span>}
                  </div>
                ))}
                <div ref={movesEndRef} />
              </div>
            )}
          </div>

          <div className="panel engine-info-panel">
            <div className="panel-header">⚡ ENGINES</div>
            <div className="engine-readout">
              <div className="readout-row">
                <span className="readout-label">WHITE</span>
                <span className="readout-val">{config.engines.find(e => e.id === config.white_engine)?.name}</span>
              </div>
              <div className="readout-row">
                <span className="readout-label">BLACK</span>
                <span className="readout-val">{config.engines.find(e => e.id === config.black_engine)?.name}</span>
              </div>
              <div className="readout-row">
                <span className="readout-label">MODE</span>
                <span className="readout-val">{config.mode === 'bot_vs_bot' ? 'AUTO' : 'MANUAL'}</span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {promoPending && (
        <div className="overlay" onClick={() => setPromoPending(null)}>
          <div className="promo-panel" onClick={(e) => e.stopPropagation()}>
            <div className="panel-header">SELECT PROMOTION</div>
            <div className="promo-grid">
              {PROMOTION_CHARS.map((c) => (
                <button key={c} className="promo-btn" onClick={() => handlePromotion(c)}>
                  {PROMOTION_DISPLAY[c]}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
