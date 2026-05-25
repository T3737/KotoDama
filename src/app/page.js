"use client";

import { useEffect, useRef, useState } from "react";

// ─── SPRITESHEET LAYOUT ────────────────────────────────────────────────────
// File: /public/game_sprites.png  (600x560px)
// Cell: 120w x 140h
// Row 0 (y=0):   Player walk  – 4 frames
// Row 1 (y=140): Player attack– 4 frames
// Row 2 (y=280): Enemy walk   – 5 frames
// Row 3 (y=420): Enemy attack – 5 frames
// ───────────────────────────────────────────────────────────────────────────

const CELL_W = 120;
const CELL_H = 140;

const ANIM = {
  PLAYER_WALK:   { row: 0, frames: 4, fps: 10 },
  PLAYER_ATTACK: { row: 1, frames: 4, fps: 18 },
  ENEMY_WALK:    { row: 2, frames: 5, fps: 8  },
  ENEMY_ATTACK:  { row: 3, frames: 5, fps: 12 },
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

    // ── Load spritesheet ──
    const sprites = new Image();
    sprites.src = "/game_sprites.png";
    let spritesLoaded = false;
    sprites.onload = () => { spritesLoaded = true; };

    const gravity = 0.7;
    const keys = {};

    // ── Animation state helpers ──
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
        ctx.scale(-1, 1);
        ctx.drawImage(
          sprites,
          anim.frame * CELL_W, anim.def.row * CELL_H, CELL_W, CELL_H,
          -(x + w), y, w, h
        );
      } else {
        ctx.drawImage(
          sprites,
          anim.frame * CELL_W, anim.def.row * CELL_H, CELL_W, CELL_H,
          x, y, w, h
        );
      }
      ctx.restore();
    }

    // ── Player ──
    const player = {
      x: 100, y: 100,
      width: 40, height: 56,
      velX: 0, velY: 0,
      speed: 5, jumpPower: -14,
      grounded: false,
      facing: 1,          // 1=right, -1=left
      attacking: false,
      attackCooldown: 0,
      jumps: 0,
      invincible: 0,
      anim: makeAnim(ANIM.PLAYER_WALK),
    };

    // ── World ──
    const camera = { x: 0 };

    const platforms = [
      { x: 0,    y: 650, width: 2200, height: 50 },
      { x: 300,  y: 220, width: 200,  height: 20 },
      { x: 650,  y: 430, width: 200,  height: 20 },
      { x: 1050, y: 330, width: 200,  height: 20 },
      { x: 1450, y: 500, width: 250,  height: 20 },
    ];

    const enemies = [
      {
        x: 900, y: 610, width: 40, height: 48,
        dir: 1, alive: true,
        anim: makeAnim(ANIM.ENEMY_WALK),
        attackAnim: makeAnim(ANIM.ENEMY_ATTACK),
        isAttacking: false,
        attackTimer: 0,
      },
    ];

    const upgrade = { x: 1120, y: 280, width: 30, height: 30, collected: false, bob: 0 };
    const lockedGate = { x: 1700, y: 500, width: 60, height: 150 };

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

    // ── Collision helpers ──
    function rectsCollide(a, b) {
      return a.x < b.x + b.width && a.x + a.width > b.x &&
             a.y < b.y + b.height && a.y + a.height > b.y;
    }

    function resolvePlatformsVertical(obj) {
      for (const p of platforms) {
        if (
          obj.x < p.x + p.width && obj.x + obj.width > p.x &&
          obj.y + obj.height >= p.y &&
          obj.y + obj.height <= p.y + p.height + Math.abs(obj.velY) + 2
        ) {
          if (obj.velY >= 0) {
            obj.y = p.y - obj.height;
            obj.velY = 0;
            obj.grounded = true;
            obj.jumps = 0;
          }
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
      const swordHitbox = {
        x: player.facing === 1 ? player.x + player.width : player.x - 50,
        y: player.y + 10,
        width: 50, height: 30,
      };
      for (const enemy of enemies) {
        if (!enemy.alive) continue;
        if (rectsCollide(swordHitbox, enemy)) {
          enemy.alive = false;
          spawnParticles(enemy.x + enemy.width / 2, enemy.y + enemy.height / 2, "#ff4444", 12);
        }
      }
    }

    // ── Main loop ──
    let animId;
    let lastTime = performance.now();

    function update(now) {
      const dt = Math.min(now - lastTime, 50); // cap at 50ms
      lastTime = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // ── Player input ──
      player.velX = 0;
      const moving = keys["a"] || keys["ArrowLeft"] || keys["d"] || keys["ArrowRight"];

      if (keys["a"] || keys["ArrowLeft"]) { player.velX = -player.speed; player.facing = -1; }
      if (keys["d"] || keys["ArrowRight"]) { player.velX =  player.speed; player.facing =  1; }

      // ── Attack cooldown ──
      if (player.attackCooldown > 0) player.attackCooldown -= dt;

      // ── Player animation state machine ──
      if (player.attacking) {
        tickAnim(player.anim, dt);
        if (player.anim.done) {
          player.attacking = false;
          resetAnim(player.anim, ANIM.PLAYER_WALK);
        }
      } else {
        if (moving || !player.grounded) {
          if (player.anim.def !== ANIM.PLAYER_WALK) resetAnim(player.anim, ANIM.PLAYER_WALK);
          tickAnim(player.anim, dt);
        } else {
          // idle: hold frame 0 of walk
          player.anim.frame = 0;
        }
      }

      // ── Horizontal movement ──
      player.x += player.velX;
      for (const p of platforms) {
        if (rectsCollide(player, p)) {
          if (player.velX > 0) player.x = p.x - player.width;
          else if (player.velX < 0) player.x = p.x + p.width;
        }
      }

      // ── Vertical movement ──
      player.velY += gravity;
      player.y += player.velY;
      player.grounded = false;
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

        enemy.x += enemy.dir * 2;
        if (enemy.x > 1050 || enemy.x < 750) enemy.dir *= -1;

        // enemy attack anim timer
        if (enemy.isAttacking) {
          tickAnim(enemy.attackAnim, dt);
          if (enemy.attackAnim.done) {
            enemy.isAttacking = false;
            resetAnim(enemy.anim, ANIM.ENEMY_WALK);
          }
        } else {
          tickAnim(enemy.anim, dt);
          // trigger attack if near player
          const dist = Math.abs(enemy.x - player.x);
          enemy.attackTimer -= dt;
          if (dist < 60 && enemy.attackTimer <= 0) {
            enemy.isAttacking = true;
            resetAnim(enemy.attackAnim, ANIM.ENEMY_ATTACK);
            enemy.attackTimer = 1200;
          }
        }

        if (rectsCollide(player, enemy) && player.invincible <= 0) {
          const newHealth = Math.max(healthRef.current - 1, 0);
          healthRef.current = newHealth;
          setHealth(newHealth);
          player.invincible = 90;
          player.velX = player.facing * -4;
          player.velY = -7;
          spawnParticles(player.x + player.width / 2, player.y, "#ff8800", 8);
        }
      }

      if (player.invincible > 0) player.invincible--;

      // ── Upgrade ──
      upgrade.bob = Math.sin(Date.now() / 400) * 5;
      if (rectsCollide(player, upgrade) && !upgrade.collected) {
        upgrade.collected = true;
        doubleJumpRef.current = true;
        setDoubleJumpUnlocked(true);
        spawnParticles(upgrade.x + 15, upgrade.y + 15, "#00ffff", 16);
      }

      // ── Particles ──
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.15;
        p.life -= 0.035;
        if (p.life <= 0) particles.splice(i, 1);
      }

      // ── Camera ──
      camera.x = Math.max(0, player.x - 300);

      // ═══════════════════════════════════════════
      //  DRAW
      // ═══════════════════════════════════════════
      ctx.save();
      ctx.translate(-camera.x, 0);

      // Background gradient
      const bg = ctx.createLinearGradient(camera.x, 0, camera.x, canvas.height);
      bg.addColorStop(0, "#0a0a1a");
      bg.addColorStop(1, "#1a1020");
      ctx.fillStyle = bg;
      ctx.fillRect(camera.x, 0, canvas.width, canvas.height);

      // Background stars
      ctx.fillStyle = "rgba(255,255,255,0.4)";
      for (let i = 0; i < 60; i++) {
        const sx = ((i * 337 + camera.x * 0.1) % 2200);
        const sy = (i * 197) % 640;
        ctx.fillRect(sx, sy, 1.5, 1.5);
      }

      // Platforms
      for (const p of platforms) {
        const grad = ctx.createLinearGradient(p.x, p.y, p.x, p.y + p.height);
        grad.addColorStop(0, "#5a5a7a");
        grad.addColorStop(1, "#2a2a3a");
        ctx.fillStyle = grad;
        ctx.fillRect(p.x, p.y, p.width, p.height);
        // top edge highlight
        ctx.fillStyle = "rgba(150,150,200,0.4)";
        ctx.fillRect(p.x, p.y, p.width, 3);
      }

      // Gate
      const gateColor = doubleJumpRef.current ? "#00cc44" : "#880000";
      ctx.fillStyle = gateColor;
      ctx.fillRect(lockedGate.x, lockedGate.y, lockedGate.width, lockedGate.height);
      ctx.fillStyle = "rgba(255,255,255,0.15)";
      ctx.fillRect(lockedGate.x + 5, lockedGate.y + 5, 10, lockedGate.height - 10);
      ctx.fillStyle = doubleJumpRef.current ? "#aaffcc" : "#ffaaaa";
      ctx.font = "bold 11px monospace";
      ctx.textAlign = "center";
      ctx.fillText(doubleJumpRef.current ? "OPEN" : "LOCK", lockedGate.x + 30, lockedGate.y + lockedGate.height / 2);
      ctx.textAlign = "left";

      // Upgrade orb
      if (!upgrade.collected) {
        const orbY = upgrade.y + upgrade.bob;
        const glow = ctx.createRadialGradient(
          upgrade.x + 15, orbY + 15, 2,
          upgrade.x + 15, orbY + 15, 20
        );
        glow.addColorStop(0, "rgba(0,255,255,0.6)");
        glow.addColorStop(1, "rgba(0,255,255,0)");
        ctx.fillStyle = glow;
        ctx.fillRect(upgrade.x - 10, orbY - 10, 60, 60);
        ctx.fillStyle = "cyan";
        ctx.beginPath();
        ctx.arc(upgrade.x + 15, orbY + 15, 12, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "white";
        ctx.font = "bold 14px monospace";
        ctx.textAlign = "center";
        ctx.fillText("2J", upgrade.x + 15, orbY + 20);
        ctx.textAlign = "left";
      }

      // Enemies
      for (const enemy of enemies) {
        if (!enemy.alive) continue;
        const curAnim = enemy.isAttacking ? enemy.attackAnim : enemy.anim;
        const flipEnemy = enemy.dir < 0;
        drawSprite(curAnim, enemy.x - 30, enemy.y - 48, CELL_W * 0.8, CELL_H * 0.8, flipEnemy);
      }

      // Player
      const flipPlayer = player.facing === -1;
      const playerAlpha = player.invincible > 0
        ? (Math.floor(player.invincible / 5) % 2 === 0 ? 0.4 : 1.0)
        : 1.0;

      // draw sprite centered on hitbox
      const spriteW = CELL_W * 0.9;
      const spriteH = CELL_H * 0.9;
      const spriteX = player.x + (player.width - spriteW) / 2;
      const spriteY = player.y + player.height - spriteH;
      drawSprite(player.anim, spriteX, spriteY, spriteW, spriteH, flipPlayer, playerAlpha);

      // Particles
      for (const p of particles) {
        ctx.globalAlpha = p.life;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      ctx.restore();

      // ─── HUD ───
      // Health bar
      const barW = 150, barH = 20;
      const barX = 20, barY = 20;
      ctx.fillStyle = "#333";
      ctx.fillRect(barX, barY, barW, barH);
      const hpRatio = healthRef.current / 5;
      const barColor = hpRatio > 0.6 ? "#44dd44" : hpRatio > 0.3 ? "#ddaa00" : "#dd2222";
      ctx.fillStyle = barColor;
      ctx.fillRect(barX, barY, barW * hpRatio, barH);
      ctx.strokeStyle = "#888";
      ctx.lineWidth = 1;
      ctx.strokeRect(barX, barY, barW, barH);
      ctx.fillStyle = "white";
      ctx.font = "bold 13px monospace";
      ctx.fillText(`HP ${healthRef.current}/5`, barX + 4, barY + 14);

      // Double jump badge
      ctx.fillStyle = doubleJumpRef.current ? "rgba(0,200,100,0.85)" : "rgba(80,80,80,0.85)";
      ctx.fillRect(20, 50, 160, 24);
      ctx.fillStyle = "white";
      ctx.font = "13px monospace";
      ctx.fillText(`2x JUMP: ${doubleJumpRef.current ? "UNLOCKED ✓" : "locked"}`, 26, 66);

      // Controls hint
      ctx.fillStyle = "rgba(255,255,255,0.3)";
      ctx.font = "11px monospace";
      ctx.fillText("WASD/↑ move+jump  J=attack", 20, canvas.height - 12);

      animId = requestAnimationFrame(update);
    }

    function keyDown(e) {
      keys[e.key] = true;

      if (e.key === "w" || e.key === "ArrowUp" || e.key === " ") {
        const maxJumps = doubleJumpRef.current ? 2 : 1;
        if (player.jumps < maxJumps) {
          player.velY = player.jumpPower;
          player.jumps++;
          e.preventDefault();
        }
      }

      if (e.key === "j" && !player.attacking && player.attackCooldown <= 0) {
        player.attacking = true;
        player.attackCooldown = 300;
        resetAnim(player.anim, ANIM.PLAYER_ATTACK);
        attackHitEnemies();
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
    <main className="w-screen h-screen bg-black flex flex-col items-center justify-center overflow-hidden">
      <canvas ref={canvasRef} className="border border-zinc-800 rounded-xl shadow-2xl" />
    </main>
  );
}