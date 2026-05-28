"use client";

import { useEffect, useRef, useState } from "react";

// ─── SPRITESHEET: /public/game_sprites.png (500x720px) ───────────────────
// Cell: 100w x 120h
// Row 0 (y=0):   player idle   – 4 frames
// Row 1 (y=120): player walk   – 5 frames
// Row 2 (y=240): player attack – 3 frames
// Row 3 (y=360): player jump   – 4 frames
// Row 4 (y=480): enemy idle    – 4 frames
// Row 5 (y=600): enemy hit     – 3 frames
// ─────────────────────────────────────────────────────────────────────────

const CELL_W = 100;
const CELL_H = 120;

const ANIM = {
  PLAYER_IDLE:   { row: 0, frames: 4, fps: 6  },
  PLAYER_WALK:   { row: 1, frames: 5, fps: 10 },
  PLAYER_ATTACK: { row: 2, frames: 3, fps: 14 },
  PLAYER_JUMP:   { row: 3, frames: 4, fps: 10 },
  ENEMY_IDLE:    { row: 4, frames: 4, fps: 6  },
  ENEMY_HIT:     { row: 5, frames: 3, fps: 12 },
};

export default function Home() {
  const canvasRef = useRef(null);
  const healthRef = useRef(5);
  const doubleJumpRef = useRef(false);
  const [health, setHealth] = useState(5);
  const [doubleJumpUnlocked, setDoubleJumpUnlocked] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    canvas.width = 1200;
    canvas.height = 700;

    // ── Load assets ──
    const spriteSheet = new Image();
    spriteSheet.src = "/game_sprites.png";
    let spritesLoaded = false;
    spriteSheet.onload = () => { spritesLoaded = true; };

    const bgImage = new Image();
    bgImage.src = "/game_bg.png";
    let bgLoaded = false;
    bgImage.onload = () => { bgLoaded = true; };

    const gravity = 0.7;
    const keys = {};

    // ── Anim helpers ──
    function makeAnim(def) {
      return { def, frame: 0, timer: 0, done: false };
    }
    function tickAnim(anim, dt) {
      anim.timer += dt;
      const interval = 1000 / anim.def.fps;
      if (anim.timer >= interval) {
        anim.timer -= interval;
        anim.frame++;
        if (anim.frame >= anim.def.frames) {
          anim.frame = anim.def.frames - 1;
          anim.done = true;
        }
      }
    }
    function loopAnim(anim, dt) {
      anim.timer += dt;
      const interval = 1000 / anim.def.fps;
      if (anim.timer >= interval) {
        anim.timer -= interval;
        anim.frame = (anim.frame + 1) % anim.def.frames;
      }
    }
    function resetAnim(anim, def) {
      anim.def = def;
      anim.frame = 0;
      anim.timer = 0;
      anim.done = false;
    }
    function drawSprite(anim, x, y, w, h, flipX, alpha = 1) {
      if (!spritesLoaded) return;
      ctx.save();
      ctx.globalAlpha = alpha;
      if (flipX) {
        ctx.translate(x + w, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(
          spriteSheet,
          anim.frame * CELL_W, anim.def.row * CELL_H, CELL_W, CELL_H,
          0, y, w, h
        );
      } else {
        ctx.drawImage(
          spriteSheet,
          anim.frame * CELL_W, anim.def.row * CELL_H, CELL_W, CELL_H,
          x, y, w, h
        );
      }
      ctx.restore();
    }

    // ── Player ──
    const player = {
      x: 80, y: 500,
      width: 38, height: 58,
      velX: 0, velY: 0,
      speed: 5, jumpPower: -15,
      grounded: false,
      facing: 1,
      attacking: false,
      attackCooldown: 0,
      jumps: 0,
      invincible: 0,
      anim: makeAnim(ANIM.PLAYER_IDLE),
    };

    const camera = { x: 0 };

    // Rock-style platforms drawn with canvas (mossy stone look)
    const platforms = [
      { x: 0,    y: 640, width: 2400, height: 60 },  // ground
      { x: 280,  y: 500, width: 220,  height: 28 },  // low left
      { x: 620,  y: 400, width: 200,  height: 28 },  // mid
      { x: 1020, y: 300, width: 220,  height: 28 },  // high right
      { x: 1420, y: 470, width: 260,  height: 28 },  // far right
    ];

    const enemies = [
      {
        x: 850, y: 600, width: 44, height: 44,
        dir: 1, alive: true,
        anim: makeAnim(ANIM.ENEMY_IDLE),
        hitAnim: makeAnim(ANIM.ENEMY_HIT),
        isHit: false,
        hitTimer: 0,
        attackTimer: 0,
      },
      {
        x: 1100, y: 260, width: 44, height: 44,
        dir: -1, alive: true,
        anim: makeAnim(ANIM.ENEMY_IDLE),
        hitAnim: makeAnim(ANIM.ENEMY_HIT),
        isHit: false,
        hitTimer: 0,
        attackTimer: 0,
      },
    ];

    const upgrade = {
      x: 1080, y: 245, width: 28, height: 28,
      collected: false, bob: 0,
    };
    const lockedGate = { x: 1750, y: 480, width: 60, height: 160 };

    // ── Particles ──
    const particles = [];
    function spawnParticles(x, y, color, count = 8) {
      for (let i = 0; i < count; i++) {
        const angle = (Math.PI * 2 * i) / count + Math.random() * 0.5;
        const speed = 2 + Math.random() * 3;
        particles.push({
          x, y,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 2,
          life: 1,
          color,
          size: 3 + Math.random() * 4,
        });
      }
    }

    // ── Collision ──
    function rectsCollide(a, b) {
      return a.x < b.x + b.width && a.x + a.width > b.x &&
             a.y < b.y + b.height && a.y + a.height > b.y;
    }

    function resolvePlatformsVertical(obj) {
      obj.grounded = false;
      for (const p of platforms) {
        if (
          obj.x < p.x + p.width && obj.x + obj.width > p.x &&
          obj.y + obj.height >= p.y &&
          obj.y + obj.height <= p.y + p.height + Math.abs(obj.velY) + 2 &&
          obj.velY >= 0
        ) {
          obj.y = p.y - obj.height;
          obj.velY = 0;
          obj.grounded = true;
          obj.jumps = 0;
        }
        // ceiling
        if (
          obj.x < p.x + p.width && obj.x + obj.width > p.x &&
          obj.y <= p.y + p.height && obj.y >= p.y && obj.velY < 0
        ) {
          obj.y = p.y + p.height;
          obj.velY = 0;
        }
      }
    }

    function attackHitEnemies() {
      const reach = 55;
      const hitbox = {
        x: player.facing === 1 ? player.x + player.width : player.x - reach,
        y: player.y + 8,
        width: reach,
        height: 32,
      };
      for (const enemy of enemies) {
        if (!enemy.alive) continue;
        if (rectsCollide(hitbox, enemy)) {
          enemy.alive = false;
          spawnParticles(
            enemy.x + enemy.width / 2,
            enemy.y + enemy.height / 2,
            "#55ff55", 14
          );
        }
      }
    }

    // ── Draw rock platform ──
    function drawPlatform(p) {
      // Base stone
      ctx.fillStyle = "#4a4a52";
      ctx.fillRect(p.x, p.y, p.width, p.height);
      // Darker bottom
      ctx.fillStyle = "#2e2e35";
      ctx.fillRect(p.x, p.y + p.height - 8, p.width, 8);
      // Top moss strip
      ctx.fillStyle = "#3a6b2a";
      ctx.fillRect(p.x, p.y, p.width, 5);
      // Lighter moss highlights
      ctx.fillStyle = "#4e8c38";
      for (let mx = p.x + 4; mx < p.x + p.width - 4; mx += 16) {
        ctx.fillRect(mx, p.y, 8, 3);
      }
      // Stone crack lines
      ctx.fillStyle = "#38383f";
      for (let cx = p.x + 20; cx < p.x + p.width - 10; cx += 30) {
        ctx.fillRect(cx, p.y + 7, 2, p.height - 10);
      }
      // Top highlight edge
      ctx.fillStyle = "rgba(200,200,180,0.18)";
      ctx.fillRect(p.x, p.y, p.width, 2);
    }

    // ── Main loop ──
    let animId;
    let lastTime = performance.now();

    function update(now) {
      const dt = Math.min(now - lastTime, 50);
      lastTime = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // ── Input ──
      player.velX = 0;
      const moving = keys["a"] || keys["ArrowLeft"] || keys["d"] || keys["ArrowRight"];
      if (keys["a"] || keys["ArrowLeft"]) { player.velX = -player.speed; player.facing = -1; }
      if (keys["d"] || keys["ArrowRight"]) { player.velX =  player.speed; player.facing =  1; }

      if (player.attackCooldown > 0) player.attackCooldown -= dt;

      // ── Player anim state machine ──
      if (player.attacking) {
        tickAnim(player.anim, dt);
        if (player.anim.done) {
          player.attacking = false;
          resetAnim(player.anim, ANIM.PLAYER_IDLE);
        }
      } else if (!player.grounded) {
        if (player.anim.def !== ANIM.PLAYER_JUMP) resetAnim(player.anim, ANIM.PLAYER_JUMP);
        tickAnim(player.anim, dt);
      } else if (moving) {
        if (player.anim.def !== ANIM.PLAYER_WALK) resetAnim(player.anim, ANIM.PLAYER_WALK);
        loopAnim(player.anim, dt);
      } else {
        if (player.anim.def !== ANIM.PLAYER_IDLE) resetAnim(player.anim, ANIM.PLAYER_IDLE);
        loopAnim(player.anim, dt);
      }

      // ── Horizontal ──
      player.x += player.velX;
      for (const p of platforms) {
        if (rectsCollide(player, p)) {
          if (player.velX > 0) player.x = p.x - player.width;
          else if (player.velX < 0) player.x = p.x + p.width;
        }
      }
      player.x = Math.max(0, player.x);

      // ── Vertical ──
      player.velY += gravity;
      player.y += player.velY;
      resolvePlatformsVertical(player);

      // ── Gate ──
      if (rectsCollide(player, lockedGate) && !doubleJumpRef.current) {
        player.x = player.facing === 1
          ? lockedGate.x - player.width
          : lockedGate.x + lockedGate.width;
      }

      // ── Enemies ──
      for (const enemy of enemies) {
        if (!enemy.alive) continue;

        enemy.x += enemy.dir * 1.5;

        // Patrol bounds per enemy
        const patrolMin = enemy === enemies[0] ? 700 : 1020;
        const patrolMax = enemy === enemies[0] ? 1000 : 1240;
        if (enemy.x > patrolMax || enemy.x < patrolMin) enemy.dir *= -1;

        if (enemy.isHit) {
          tickAnim(enemy.hitAnim, dt);
          if (enemy.hitAnim.done) {
            enemy.isHit = false;
            resetAnim(enemy.anim, ANIM.ENEMY_IDLE);
          }
        } else {
          loopAnim(enemy.anim, dt);
        }

        enemy.attackTimer -= dt;
        if (rectsCollide(player, enemy) && player.invincible <= 0 && enemy.attackTimer <= 0) {
          const newHP = Math.max(healthRef.current - 1, 0);
          healthRef.current = newHP;
          setHealth(newHP);
          player.invincible = 90;
          player.velY = -7;
          player.velX = player.facing * -5;
          enemy.attackTimer = 1000;
          spawnParticles(player.x + player.width / 2, player.y, "#ff6600", 10);
        }
      }
      if (player.invincible > 0) player.invincible--;

      // ── Upgrade ──
      upgrade.bob = Math.sin(Date.now() / 380) * 5;
      if (!upgrade.collected && rectsCollide(player, upgrade)) {
        upgrade.collected = true;
        doubleJumpRef.current = true;
        setDoubleJumpUnlocked(true);
        spawnParticles(upgrade.x + 14, upgrade.y + 14, "#00eeff", 18);
      }

      // ── Particles ──
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx; p.y += p.vy;
        p.vy += 0.15;
        p.life -= 0.03;
        if (p.life <= 0) particles.splice(i, 1);
      }

      // ── Camera ──
      camera.x = Math.max(0, Math.min(player.x - 300, 2400 - canvas.width));

      // ════════════════════════════════
      //  DRAW
      // ════════════════════════════════
      ctx.save();
      ctx.translate(-camera.x, 0);

      // ── Background (parallax: scroll at 40% speed) ──
      if (bgLoaded) {
        const bgX = -camera.x * 0.4;
        // tile bg horizontally if needed
        const bgW = bgImage.width;
        const bgH = bgImage.height;
        const startTile = Math.floor(-bgX / bgW);
        const endTile = Math.ceil((canvas.width - bgX) / bgW) + startTile;
        for (let t = startTile; t <= endTile; t++) {
          ctx.drawImage(bgImage, bgX + t * bgW + camera.x, 0, bgW, canvas.height);
        }
      } else {
        // Fallback gradient
        const bg = ctx.createLinearGradient(camera.x, 0, camera.x, canvas.height);
        bg.addColorStop(0, "#1a1a2e");
        bg.addColorStop(1, "#16213e");
        ctx.fillStyle = bg;
        ctx.fillRect(camera.x, 0, canvas.width, canvas.height);
      }

      // ── Platforms (mossy rock style) ──
      for (const p of platforms) drawPlatform(p);

      // ── Gate ──
      const gateOpen = doubleJumpRef.current;
      ctx.fillStyle = gateOpen ? "#1a6b3a" : "#6b1a1a";
      ctx.fillRect(lockedGate.x, lockedGate.y, lockedGate.width, lockedGate.height);
      // Gate bars
      ctx.fillStyle = gateOpen ? "#2aaa5a" : "#aa2a2a";
      for (let bx = lockedGate.x + 8; bx < lockedGate.x + lockedGate.width - 4; bx += 14) {
        ctx.fillRect(bx, lockedGate.y, 5, lockedGate.height);
      }
      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.font = "bold 10px monospace";
      ctx.textAlign = "center";
      ctx.fillText(gateOpen ? "OPEN" : "LOCK", lockedGate.x + 30, lockedGate.y + lockedGate.height / 2 + 4);
      ctx.textAlign = "left";

      // ── Upgrade orb ──
      if (!upgrade.collected) {
        const oy = upgrade.y + upgrade.bob;
        // Glow
        const glow = ctx.createRadialGradient(
          upgrade.x + 14, oy + 14, 2,
          upgrade.x + 14, oy + 14, 22
        );
        glow.addColorStop(0, "rgba(0,220,255,0.7)");
        glow.addColorStop(1, "rgba(0,220,255,0)");
        ctx.fillStyle = glow;
        ctx.fillRect(upgrade.x - 10, oy - 10, 56, 56);
        ctx.fillStyle = "#00ddff";
        ctx.beginPath();
        ctx.arc(upgrade.x + 14, oy + 14, 11, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "white";
        ctx.font = "bold 10px monospace";
        ctx.textAlign = "center";
        ctx.fillText("2↑", upgrade.x + 14, oy + 18);
        ctx.textAlign = "left";
      }

      // ── Enemies ──
      for (const enemy of enemies) {
        if (!enemy.alive) continue;
        const curAnim = enemy.isHit ? enemy.hitAnim : enemy.anim;
        const flip = enemy.dir < 0;
        const sw = CELL_W * 0.85;
        const sh = CELL_H * 0.85;
        drawSprite(curAnim, enemy.x - sw * 0.3, enemy.y - sh * 0.5, sw, sh, flip);
      }

      // ── Player ──
      const flipPlayer = player.facing === -1;
      const pAlpha = player.invincible > 0
        ? (Math.floor(player.invincible / 5) % 2 === 0 ? 0.35 : 1.0)
        : 1.0;
      const sw = CELL_W * 1.1;
      const sh = CELL_H * 1.1;
      const sx = player.x + (player.width - sw) / 2;
      const sy = player.y + player.height - sh;
      drawSprite(player.anim, sx, sy, sw, sh, flipPlayer, pAlpha);

      // ── Particles ──
      for (const p of particles) {
        ctx.save();
        ctx.globalAlpha = p.life;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      ctx.restore(); // end camera transform

      // ════════════════════════════════
      //  HUD (no camera transform)
      // ════════════════════════════════

      // HP bar background
      const barW = 160, barH = 22;
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.fillRect(16, 16, barW + 4, barH + 4);
      ctx.fillStyle = "#222";
      ctx.fillRect(18, 18, barW, barH);
      const hpRatio = healthRef.current / 5;
      const barColor = hpRatio > 0.6 ? "#44dd44" : hpRatio > 0.3 ? "#ddaa00" : "#dd2222";
      ctx.fillStyle = barColor;
      ctx.fillRect(18, 18, barW * hpRatio, barH);
      ctx.strokeStyle = "#888";
      ctx.lineWidth = 1;
      ctx.strokeRect(18, 18, barW, barH);
      ctx.fillStyle = "white";
      ctx.font = "bold 13px monospace";
      ctx.fillText(`HP  ${healthRef.current}/5`, 24, 33);

      // Double jump badge
      ctx.fillStyle = doubleJumpRef.current
        ? "rgba(0,180,80,0.88)"
        : "rgba(60,60,60,0.80)";
      ctx.fillRect(16, 48, 172, 22);
      ctx.fillStyle = "white";
      ctx.font = "12px monospace";
      ctx.fillText(
        `2x JUMP: ${doubleJumpRef.current ? "UNLOCKED ✓" : "find the orb"}`,
        22, 63
      );

      // Controls panel bottom-left
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fillRect(12, canvas.height - 52, 290, 40);
      ctx.fillStyle = "rgba(255,255,255,0.6)";
      ctx.font = "12px monospace";
      ctx.fillText("WASD / ← →  move    W / ↑  jump", 18, canvas.height - 34);
      ctx.fillStyle = "#ffdd44";
      ctx.fillText("[ F ]  attack", 18, canvas.height - 17);

      animId = requestAnimationFrame(update);
    }

    // ── Input ──
    function keyDown(e) {
      keys[e.key] = true;

      if (["w","ArrowUp"," "].includes(e.key)) {
        const maxJumps = doubleJumpRef.current ? 2 : 1;
        if (player.jumps < maxJumps) {
          player.velY = player.jumpPower;
          player.jumps++;
          if (!player.grounded) resetAnim(player.anim, ANIM.PLAYER_JUMP);
        }
        if (e.key === " ") e.preventDefault();
      }

      if (e.key === "f" || e.key === "F") {
        if (!player.attacking && player.attackCooldown <= 0) {
          player.attacking = true;
          player.attackCooldown = 320;
          resetAnim(player.anim, ANIM.PLAYER_ATTACK);
          // Hit check on frame 1 (slight delay feels better)
          setTimeout(attackHitEnemies, 80);
        }
      }
    }

    function keyUp(e) { keys[e.key] = false; }

    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    animId = requestAnimationFrame(update);

    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <main className="w-screen h-screen bg-black flex items-center justify-center overflow-hidden">
      <canvas
        ref={canvasRef}
        className="border border-zinc-800 rounded-xl shadow-2xl"
      />
    </main>
  );
}