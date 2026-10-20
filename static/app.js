const library = document.querySelector('#library');
const notice = document.querySelector('#notice');
let active = null;
let selected = null;
const players = [];
const key = id => `listening:v1:${id}`;
const testButton = document.querySelector('#test-sound');
const soundStatus = document.querySelector('#sound-status');
let testContext = null;
async function stopTest() {
  const context = testContext;
  testContext = null;
  if (context && context.state !== 'closed') await context.close();
  testButton.disabled = false;
}
testButton.onclick = async () => {
  testButton.disabled = true;
  if (active) active.audio.pause();
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error('Unsupported audio');
    const context = new AudioContextClass();
    testContext = context;
    await context.resume();
    if (testContext !== context) return;
    if (context.state !== 'running') throw new Error('Audio blocked');
    soundStatus.textContent = 'Playing test tones… If you hear nothing, check your device volume, tab mute, and audio output.';
    const gain = context.createGain();
    gain.connect(context.destination);
    const start = context.currentTime;
    // Fade each tone in and out to avoid clicks; keep the level comfortable.
    gain.gain.setValueAtTime(0, start);
    for (let i = 0; i < 3; i++) {
      const time = start + i * 0.5;
      gain.gain.setValueAtTime(0, time);
      gain.gain.linearRampToValueAtTime(0.15, time + 0.03);
      gain.gain.setValueAtTime(0.15, time + 0.25);
      gain.gain.linearRampToValueAtTime(0, time + 0.3);
    }
    const oscillator = context.createOscillator();
    oscillator.frequency.value = 440;
    oscillator.connect(gain);
    oscillator.onended = async () => {
      if (testContext !== context) return;
      soundStatus.textContent = 'Test finished. If you heard the tones, your sound is ready. If not, turn up your device volume, unmute this tab, check your headphones, then test again.';
      await stopTest();
    };
    oscillator.start(start);
    oscillator.stop(start + 1.4);
  } catch {
    soundStatus.textContent = 'The sound test could not play. Check your browser’s sound permissions and try again.';
    await stopTest();
  }
};
try {
  localStorage.setItem('listening:check', '1');
  localStorage.removeItem('listening:check');
} catch {
  notice.textContent = 'Enable local storage to use the listening library.';
}
function read(id, revision) {
  const value = JSON.parse(localStorage.getItem(key(id)) || '{}');
  if ((value.revision || 0) !== revision) return {phase: 'first', position: 0};
  return { phase: ['first', 'ready', 'replay', 'done', 'replay_done'].includes(value.phase) ? value.phase : 'first',
    position: Number.isFinite(value.position) && value.position >= 0 ? value.position : 0 };
}
function save(player) {
  localStorage.setItem(key(player.id), JSON.stringify({...player.state, revision: player.revision}));
}
function render(p) {
  const playing = !p.audio.paused;
  const completed = ['ready', 'done', 'replay_done'].includes(p.state.phase);
  const canReplay = p.allowReplay && completed;
  const locked = !p.allowReplay && (completed || p.state.phase === 'replay');
  p.play.disabled = locked;
  p.play.textContent = playing ? (p.allowReplay ? 'Pause' : 'Stop') : locked ? 'Completed' : canReplay ? 'Replay' : p.state.position > 0 && !p.allowReplay ? 'Continue' : 'Play';
  p.status.textContent = locked ? 'Listening complete · replay unavailable' : p.allowReplay ? 'Unlimited replay · choose any position' : 'One listen · no replay';
  p.seek.hidden = !p.allowReplay;
  p.progress.hidden = p.allowReplay;
  p.seek.disabled = !p.allowReplay || !Number.isFinite(p.audio.duration) || p.audio.duration <= 0;
  for (const button of [p.back, p.forward]) {
    button.hidden = !p.allowReplay;
    button.disabled = p.seek.disabled || p.restoring;
  }
}
async function load() {
  try {
    if (notice.textContent) { library.textContent = ''; return; }
    const response = await fetch('/api/audio');
    if (!response.ok) throw new Error('Unable to load the audio library.');
    const items = await response.json();
    library.replaceChildren();
    if (!items.length) library.textContent = 'No audio yet. Add audio files to the audio folder to get started.';
    for (const item of items) {
      const card = document.createElement('article');
      card.className = 'card';
      card.innerHTML = '<div class="info"><h2></h2><div class="status"></div><progress max="1" value="0" aria-label="Listening progress"></progress><input class="seek" type="range" min="0" max="1" step="0.001" value="0" aria-label="Audio position" hidden><div class="time status"></div></div><div class="player-controls"><button class="back stop" aria-label="Back 5 seconds" title="Back 5 seconds" hidden><svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false"><path d="M4 9a8 8 0 1 1 0 6M4 4v5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><text x="12" y="16" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">5</text></svg></button><button class="play">Play</button><button class="forward stop" aria-label="Forward 5 seconds" title="Forward 5 seconds" hidden><svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false"><path d="M20 9a8 8 0 1 0 0 6M20 4v5h-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><text x="12" y="16" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">5</text></svg></button></div>';
      card.querySelector('h2').textContent = item.name;
      const audio = new Audio();
      audio.preload = 'none';
      audio.setAttribute('controlsList', 'nodownload noplaybackrate');
      audio.disableRemotePlayback = true;
      const p = { id: item.id, revision: item.revision, allowReplay: item.allow_replay, restoring: true, audio, state: read(item.id, item.revision), play: card.querySelector('.play'), back: card.querySelector('.back'), forward: card.querySelector('.forward'), status: card.querySelector('.status'), seek: card.querySelector('.seek'), progress: card.querySelector('progress') };
      const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
      const updatePosition = () => {
        const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
        const position = audio.currentTime || 0;
        card.querySelector('progress').value = duration ? position / duration : 0;
        p.seek.value = duration ? position / duration : 0;
        card.querySelector('.time').textContent = `${formatTime(position)} / ${formatTime(duration)}`;
      };
      audio.onloadedmetadata = () => {
        if (p.state.position > 0 && Number.isFinite(audio.duration)) {
          audio.currentTime = Math.min(p.state.position, audio.duration);
          if (!p.allowReplay && p.state.position >= audio.duration) {
            p.state = {phase: 'done', position: 0};
            save(p);
          }
        }
        p.restoring = false;
        updatePosition();
        render(p);
      };
      audio.ondurationchange = () => { updatePosition(); render(p); };
      const seekTo = position => {
        if (!p.allowReplay || p.restoring || !Number.isFinite(audio.duration)) return;
        if (['ready', 'done', 'replay_done'].includes(p.state.phase)) p.state.phase = 'replay';
        audio.currentTime = Math.max(0, Math.min(position, audio.duration));
        p.state.position = audio.currentTime;
        save(p);
        updatePosition();
        render(p);
      };
      p.seek.oninput = () => seekTo(Number(p.seek.value) * audio.duration);
      p.back.onclick = () => seekTo(audio.currentTime - 5);
      p.forward.onclick = () => seekTo(audio.currentTime + 5);
      if (p.allowReplay) {
        audio.preload = 'metadata';
        audio.src = `/media/${p.id}`;
      }
      players.push(p);
      p.card = card;
      card.addEventListener('focusin', () => { selected = p; });
      card.addEventListener('pointerdown', () => { selected = p; });
      p.play.onclick = async () => {
        selected = p;
        if (!audio.paused) { audio.pause(); return; }
        try {
          const response = await fetch('/api/audio');
          if (!response.ok) throw new Error('Settings unavailable');
          const current = (await response.json()).find(item => item.id === p.id);
          if (!current) { audio.pause(); card.remove(); notice.textContent = 'This audio is no longer available.'; return; }
          const changed = p.revision !== current.revision;
          p.revision = current.revision;
          p.state = read(p.id, p.revision);
          if (changed) {
            audio.pause();
            audio.currentTime = 0;
            save(p);
            updatePosition();
          }
          p.allowReplay = current.allow_replay;
          render(p);
          if (p.play.disabled) return;
          if (['ready', 'done', 'replay_done'].includes(p.state.phase)) {
            p.state = {phase: 'replay', position: 0};
            save(p);
            audio.currentTime = 0;
          }
          await stopTest();
          if (active && active !== p) active.audio.pause();
          if (!audio.getAttribute('src')) {
            p.restoring = true;
            audio.src = `/media/${p.id}`;
          }
          active = p;
          await audio.play();
          notice.textContent = '';
        } catch { notice.textContent = 'Playback could not start. Check the audio file and try again.'; }
        render(p);
      };
      audio.onplay = () => render(p);
      audio.onpause = () => { if (!audio.ended && !p.externalUpdate && !p.restoring) { p.state.position = audio.currentTime; save(p); } p.externalUpdate = false; render(p); };
      audio.ontimeupdate = () => {
        // Loading a source can emit timeupdate at zero before saved progress is restored.
        if (audio.ended || p.restoring) return;
        p.state.position = audio.currentTime;
        save(p);
        updatePosition();
      };
      audio.onended = () => {
        p.state = { phase: p.state.phase === 'replay' ? 'replay_done' : 'done', position: 0 };
        save(p);
        render(p);
      };
      audio.onerror = () => { notice.textContent = `Unable to play “${item.name}”. The file may be missing or unsupported.`; render(p); };
      render(p);
      library.append(card);
    }
  } catch (error) { library.textContent = 'Could not load audio. Refresh to try again.'; }
}
window.addEventListener('keydown', event => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return;
  if (!['Space', 'ArrowLeft', 'ArrowRight'].includes(event.code)) return;
  const target = event.target;
  // Keep typing, range-slider navigation, and the sound-test button native.
  if (target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])') || target === testButton) return;
  const player = players.find(p => p.card.contains(target)) || selected || active || players[0];
  if (!player || !player.card.isConnected) return;
  if (event.code === 'Space') {
    event.preventDefault();
    if (!event.repeat && !player.play.disabled) player.play.click();
  } else if (player.allowReplay) {
    event.preventDefault();
    const button = event.code === 'ArrowLeft' ? player.back : player.forward;
    if (!button.disabled) button.click();
  }
});
window.addEventListener('storage', event => {
  for (const p of players) {
    if (event.key === key(p.id) || event.key === null) {
      p.externalUpdate = !p.audio.paused;
      p.audio.pause();
      p.state = read(p.id, p.revision);
      render(p);
    }
  }
});
load();
