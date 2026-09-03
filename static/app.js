// Dynamic Backend Resolver for GitHub Pages and Localhost
let API_BASE_URL = localStorage.getItem('cliptube_backend_url') || (
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
        ? '' 
        : 'http://localhost:8000'
);

function getApiUrl(path) {
    if (!API_BASE_URL) return path;
    const cleanBase = API_BASE_URL.replace(/\/+$/, '');
    const cleanPath = path.startsWith('/') ? path : '/' + path;
    return cleanBase + cleanPath;
}

// --------------------------------------------------------------------------
// ClipTube PRO - Client Application Logic
// --------------------------------------------------------------------------

let ytPlayer = null;
let currentVideoData = null;
let activeTaskId = null;
let pollTimer = null;
let playerTimeInterval = null;
let activeMode = 'trim-video';
let deferredPrompt = null;
let hasAutoDownloaded = false;
let ytApiReady = false;       // true once YouTube IFrame API has loaded
let pendingVideoId = null;    // holds a video ID if Load Video clicked before API ready

const ytUrlInput = document.getElementById('ytUrlInput');
const clearUrlBtn = document.getElementById('clearUrlBtn');
const fetchInfoBtn = document.getElementById('fetchInfoBtn');
const mainWorkspace = document.getElementById('mainWorkspace');
const playerPlaceholder = document.getElementById('playerPlaceholder');
const ytPlayerContainer = document.getElementById('ytPlayerContainer');
const liveStatusTag = document.getElementById('liveStatusTag');
const unlockStreamRangeBtn = document.getElementById('unlockStreamRangeBtn');

const videoThumb = document.getElementById('videoThumb');
const videoTitle = document.getElementById('videoTitle');
const videoUploader = document.getElementById('videoUploader');
const videoDurationStr = document.getElementById('videoDurationStr');
const selectedDurationBadge = document.getElementById('selectedDurationBadge');

const modeTabs = document.querySelectorAll('.mode-tab');
const trimmerControlsSection = document.getElementById('trimmerControlsSection');
const quickCutToolbar = document.getElementById('quickCutToolbar');

const startRange = document.getElementById('startRange');
const endRange = document.getElementById('endRange');
const timelineProgress = document.getElementById('timelineProgress');

// SEPARATE TIME BOXES
const startH = document.getElementById('startH');
const startM = document.getElementById('startM');
const startS = document.getElementById('startS');

const endH = document.getElementById('endH');
const endM = document.getElementById('endM');
const endS = document.getElementById('endS');

const stepStartSub = document.getElementById('stepStartSub');
const stepStartAdd = document.getElementById('stepStartAdd');
const stepStart15mSub = document.getElementById('stepStart15mSub');
const stepStart15mAdd = document.getElementById('stepStart15mAdd');
const stepStart1hSub = document.getElementById('stepStart1hSub');
const stepStart1hAdd = document.getElementById('stepStart1hAdd');

const stepEndSub = document.getElementById('stepEndSub');
const stepEndAdd = document.getElementById('stepEndAdd');
const stepEnd15mSub = document.getElementById('stepEnd15mSub');
const stepEnd15mAdd = document.getElementById('stepEnd15mAdd');
const stepEnd1hSub = document.getElementById('stepEnd1hSub');
const stepEnd1hAdd = document.getElementById('stepEnd1hAdd');

const setStartBtn = document.getElementById('setStartBtn');
const setEndBtn = document.getElementById('setEndBtn');
const previewSegmentBtn = document.getElementById('previewSegmentBtn');
const currentStartPreview = document.getElementById('currentStartPreview');
const currentEndPreview = document.getElementById('currentEndPreview');

const formatSelect = document.getElementById('formatSelect');
const qualityGroup = document.getElementById('qualityGroup');
const qualitySelect = document.getElementById('qualitySelect');
const startTrimBtn = document.getElementById('startTrimBtn');
const ctaBtnText = document.getElementById('ctaBtnText');

const progressModal = document.getElementById('progressModal');
const closeModalBtn = document.getElementById('closeModalBtn');
const statusIcon = document.getElementById('statusIcon');
const statusTitle = document.getElementById('statusTitle');
const progressBarFill = document.getElementById('progressBarFill');
const progressMessage = document.getElementById('progressMessage');
const progressPct = document.getElementById('progressPct');
const etaTimeText = document.getElementById('etaTimeText');
const downloadResult = document.getElementById('downloadResult');
const downloadLinkBtn = document.getElementById('downloadLinkBtn');
const fileSizeLabel = document.getElementById('fileSizeLabel');

const historyList = document.getElementById('historyList');
const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
const sampleBtns = document.querySelectorAll('.sample-btn');

const notifyBtn = document.getElementById('notifyBtn');
const installAppBtn = document.getElementById('installAppBtn');

// --- YouTube IFrame API Ready Callback ---
// This MUST be a global function — YouTube calls it automatically when the API script loads.
window.onYouTubeIframeAPIReady = function() {
    ytApiReady = true;
    // If the user already clicked Load Video while the API was still loading, create player now
    if (pendingVideoId) {
        createYTPlayer(pendingVideoId);
        pendingVideoId = null;
    }
};

// Edge case: YT API may have already loaded before app.js ran (e.g. from cache)
if (window.YT && window.YT.Player) {
    ytApiReady = true;
}

// --- PWA & Notification Handlers ---
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(err => console.log('SW Reg Error:', err));
}

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installAppBtn) installAppBtn.classList.remove('hidden');
});

if (installAppBtn) {
    installAppBtn.addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            if (outcome === 'accepted') installAppBtn.classList.add('hidden');
            deferredPrompt = null;
        }
    });
}

if (notifyBtn) {
    notifyBtn.addEventListener('click', () => {
        if ('Notification' in window) {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    notifyBtn.innerHTML = '<i class="fa-solid fa-bell-slash"></i> Alerts Active';
                    notifyBtn.style.borderColor = 'var(--accent-green)';
                }
            });
        }
    });
}

function sendDesktopNotification(title, message) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {
            body: message,
            icon: currentVideoData ? currentVideoData.thumbnail : 'https://img.youtube.com/vi/aqz-KE-bpKQ/hqdefault.jpg'
        });
    }
}

// --- Time & Box Helpers ---
function getStartTotalSeconds() {
    const h = parseInt(startH.value) || 0;
    const m = parseInt(startM.value) || 0;
    const s = parseInt(startS.value) || 0;
    return h * 3600 + m * 60 + s;
}

function getEndTotalSeconds() {
    const h = parseInt(endH.value) || 0;
    const m = parseInt(endM.value) || 0;
    const s = parseInt(endS.value) || 0;
    return h * 3600 + m * 60 + s;
}

function setStartBoxFromSeconds(totalSec) {
    totalSec = Math.max(0, Math.floor(totalSec));
    startH.value = Math.floor(totalSec / 3600);
    startM.value = Math.floor((totalSec % 3600) / 60);
    startS.value = totalSec % 60;
}

function setEndBoxFromSeconds(totalSec) {
    totalSec = Math.max(0, Math.floor(totalSec));
    endH.value = Math.floor(totalSec / 3600);
    endM.value = Math.floor((totalSec % 3600) / 60);
    endS.value = totalSec % 60;
}

function getStartFormatted() {
    const pad = (n) => String(n || 0).padStart(2, '0');
    return `${pad(startH.value)}:${pad(startM.value)}:${pad(startS.value)}`;
}

function getEndFormatted() {
    const pad = (n) => String(n || 0).padStart(2, '0');
    return `${pad(endH.value)}:${pad(endM.value)}:${pad(endS.value)}`;
}

function formatSecondsToTimestamp(totalSeconds, forceHours = true) {
    totalSeconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const pad = (n) => String(n).padStart(2, '0');
    if (hours > 0 || forceHours) {
        return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    } else {
        return `${pad(minutes)}:${pad(seconds)}`;
    }
}

function extractYouTubeId(url) {
    if (!url) return null;
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|live\/|shorts\/|watch\?v=|\&v=)([^#\&\?]*).*/;
    const match = url.trim().match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
}

// --- Mode Switching Handler ---
modeTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        modeTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        activeMode = tab.dataset.mode;
        applyModeSettings();
    });
});

function applyModeSettings() {
    if (activeMode === 'trim-video') {
        trimmerControlsSection.classList.remove('hidden');
        quickCutToolbar.classList.remove('hidden');
        formatSelect.value = 'mp4';
        qualityGroup.classList.remove('hidden');
        ctaBtnText.textContent = "Cut & Download Video Segment";
    } else if (activeMode === 'trim-audio') {
        trimmerControlsSection.classList.remove('hidden');
        quickCutToolbar.classList.remove('hidden');
        formatSelect.value = 'mp3';
        qualityGroup.classList.add('hidden');
        ctaBtnText.textContent = "Cut & Download MP3 Audio";
    } else if (activeMode === 'full-video') {
        trimmerControlsSection.classList.add('hidden');
        quickCutToolbar.classList.add('hidden');
        formatSelect.value = 'mp4';
        qualityGroup.classList.remove('hidden');
        ctaBtnText.textContent = "Download Full Video";
    } else if (activeMode === 'full-audio') {
        trimmerControlsSection.classList.add('hidden');
        quickCutToolbar.classList.add('hidden');
        formatSelect.value = 'mp3';
        qualityGroup.classList.add('hidden');
        ctaBtnText.textContent = "Download Full MP3 Audio";
    }
}

// --- YouTube IFrame API ---
function loadYouTubePlayer(videoId) {
    ytPlayerContainer.classList.remove('hidden');
    playerPlaceholder.classList.add('hidden');

    if (ytPlayer && typeof ytPlayer.loadVideoById === 'function') {
        // Player already exists — just swap the video
        try { ytPlayer.loadVideoById(videoId); } catch (e) { console.error('loadVideoById error:', e); }
    } else if (ytApiReady || (window.YT && window.YT.Player)) {
        // API is ready (either via our flag or window.YT direct check)
        ytApiReady = true;
        createYTPlayer(videoId);
    } else {
        // API not ready yet — queue it; onYouTubeIframeAPIReady will pick it up
        pendingVideoId = videoId;
    }
}

function createYTPlayer(videoId) {
    // Reset the div because YT replaces it in-place
    ytPlayerContainer.innerHTML = '<div id="ytIframe"></div>';
    ytPlayer = new YT.Player('ytIframe', {
        videoId: videoId,
        width: '100%',
        height: '100%',
        playerVars: { 'autoplay': 0, 'rel': 0, 'modestbranding': 1, 'playsinline': 1 },
        events: {
            'onReady': onPlayerReady,
            'onStateChange': onPlayerStateChange
        }
    });
}

function onPlayerReady(event) {
    if (playerTimeInterval) clearInterval(playerTimeInterval);
    playerTimeInterval = setInterval(updatePlayerTimeTags, 300);

    try {
        const dur = ytPlayer.getDuration();
        if (dur > 0 && (!currentVideoData || !currentVideoData.duration || currentVideoData.duration < dur)) {
            setVideoDuration(dur);
        }
    } catch (e) {}
}

function onPlayerStateChange(event) {
    if (event.data === YT.PlayerState.PLAYING) {
        try {
            const dur = ytPlayer.getDuration();
            if (dur > 0 && (!currentVideoData || !currentVideoData.duration || currentVideoData.duration < dur)) {
                setVideoDuration(dur);
            }
        } catch (e) {}
    }
}

function updatePlayerTimeTags() {
    if (ytPlayer && typeof ytPlayer.getCurrentTime === 'function') {
        try {
            const curTime = ytPlayer.getCurrentTime();
            const timeFormatted = formatSecondsToTimestamp(curTime, true);
            currentStartPreview.textContent = timeFormatted;
            currentEndPreview.textContent = timeFormatted;
        } catch (e) {}
    }
}

function setVideoDuration(durationSec) {
    durationSec = Math.max(durationSec, 10);

    if (!currentVideoData) {
        currentVideoData = { duration: durationSec };
    } else {
        currentVideoData.duration = durationSec;
    }

    const durStr = formatSecondsToTimestamp(durationSec, true);
    videoDurationStr.textContent = durStr;

    startRange.min = 0;
    startRange.max = durationSec;
    endRange.min = 0;
    endRange.max = durationSec;

    if (getEndTotalSeconds() <= getStartTotalSeconds()) {
        setEndBoxFromSeconds(durationSec);
        endRange.value = durationSec;
    }

    updateTimelineUI();
}

unlockStreamRangeBtn.addEventListener('click', () => {
    const twelveHoursInSec = 12 * 3600;
    setVideoDuration(twelveHoursInSec);
    alert('Unlocked 12-Hour Live Stream Timeline! You can set timestamps up to 12:00:00.');
});

// --- Metadata Fetcher ---
function fetchVideoData(url) {
    if (!url || !url.trim()) {
        alert('Please paste a valid YouTube video or live stream link.');
        return;
    }

    const cleanUrl = url.trim();
    const videoId = extractYouTubeId(cleanUrl);

    if (!videoId) {
        alert('Could not detect a valid YouTube Video ID. Please check the URL.');
        return;
    }

    // ── INSTANT: show workspace & load player immediately, NO server call needed ──
    currentVideoData = { id: videoId, url: cleanUrl, duration: 0 };

    mainWorkspace.classList.remove('hidden');
    videoTitle.textContent = 'Loading title...';
    videoUploader.innerHTML = '<i class="fa-solid fa-user"></i> YouTube Channel';
    videoThumb.src = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;

    // Default 3-hour timeline; player's onReady will report real duration
    setVideoDuration(3 * 3600);
    loadYouTubePlayer(videoId);
    mainWorkspace.scrollIntoView({ behavior: 'smooth' });

    // ── BACKGROUND: quietly fetch title/uploader from server (never blocks UI) ──
    fetch(getApiUrl('/api/info'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: cleanUrl }),
        signal: AbortSignal.timeout ? AbortSignal.timeout(8000) : undefined
    })
    .then(r => r.ok ? r.json() : null)
    .then(data => {
        if (!data) return;
        if (data.title && data.title !== 'YouTube Video') {
            videoTitle.textContent = data.title;
        } else {
            videoTitle.textContent = 'YouTube Video';
        }
        if (data.uploader) {
            videoUploader.innerHTML = `<i class="fa-solid fa-user"></i> ${data.uploader}`;
        }
        if (data.duration && data.duration > 0) {
            setVideoDuration(data.duration);
        }
        if (data.is_live) {
            liveStatusTag.classList.remove('hidden');
        }
        if (data.thumbnail) {
            videoThumb.src = data.thumbnail;
        }
    })
    .catch(() => {
        // silently ignore — player already loaded anyway
        videoTitle.textContent = 'YouTube Video';
    });
}


// --- Sliders & Timeline ---
function updateTimelineUI() {
    const maxSec = (currentVideoData && currentVideoData.duration > 0) ? currentVideoData.duration : (12 * 3600);

    let startSec = getStartTotalSeconds();
    let endSec = getEndTotalSeconds();

    startSec = Math.max(0, Math.min(startSec, maxSec));
    endSec = Math.max(startSec + 1, Math.min(endSec, maxSec));

    startRange.value = startSec;
    endRange.value = endSec;

    const startPct = (startSec / maxSec) * 100;
    const endPct = (endSec / maxSec) * 100;

    timelineProgress.style.left = `${startPct}%`;
    timelineProgress.style.width = `${Math.max(1, endPct - startPct)}%`;

    const diff = endSec - startSec;
    selectedDurationBadge.textContent = `Selected: ${formatSecondsToTimestamp(diff, true)}`;
}

startRange.addEventListener('input', () => {
    let startSec = parseFloat(startRange.value);
    let endSec = parseFloat(endRange.value);
    if (startSec >= endSec) {
        startSec = Math.max(0, endSec - 1);
        startRange.value = startSec;
    }
    setStartBoxFromSeconds(startSec);
    updateTimelineUI();
});

endRange.addEventListener('input', () => {
    let startSec = parseFloat(startRange.value);
    let endSec = parseFloat(endRange.value);
    if (endSec <= startSec) {
        endSec = startSec + 1;
        endRange.value = endSec;
    }
    setEndBoxFromSeconds(endSec);
    updateTimelineUI();
});

[startH, startM, startS].forEach(input => input.addEventListener('input', updateTimelineUI));
[endH, endM, endS].forEach(input => input.addEventListener('input', updateTimelineUI));

function adjustStartSeconds(delta) {
    let curSec = getStartTotalSeconds() + delta;
    setStartBoxFromSeconds(curSec);
    updateTimelineUI();
}

function adjustEndSeconds(delta) {
    let curSec = getEndTotalSeconds() + delta;
    setEndBoxFromSeconds(curSec);
    updateTimelineUI();
}

stepStartSub.addEventListener('click', () => adjustStartSeconds(-5));
stepStartAdd.addEventListener('click', () => adjustStartSeconds(5));
stepStart15mSub.addEventListener('click', () => adjustStartSeconds(-900));
stepStart15mAdd.addEventListener('click', () => adjustStartSeconds(900));
stepStart1hSub.addEventListener('click', () => adjustStartSeconds(-3600));
stepStart1hAdd.addEventListener('click', () => adjustStartSeconds(3600));

stepEndSub.addEventListener('click', () => adjustEndSeconds(-5));
stepEndAdd.addEventListener('click', () => adjustEndSeconds(5));
stepEnd15mSub.addEventListener('click', () => adjustEndSeconds(-900));
stepEnd15mAdd.addEventListener('click', () => adjustEndSeconds(900));
stepEnd1hSub.addEventListener('click', () => adjustEndSeconds(-3600));
stepEnd1hAdd.addEventListener('click', () => adjustEndSeconds(3600));

setStartBtn.addEventListener('click', () => {
    if (ytPlayer && typeof ytPlayer.getCurrentTime === 'function') {
        const curTime = ytPlayer.getCurrentTime();
        setStartBoxFromSeconds(curTime);
        updateTimelineUI();
    }
});

setEndBtn.addEventListener('click', () => {
    if (ytPlayer && typeof ytPlayer.getCurrentTime === 'function') {
        const curTime = ytPlayer.getCurrentTime();
        setEndBoxFromSeconds(curTime);
        updateTimelineUI();
    }
});

previewSegmentBtn.addEventListener('click', () => {
    if (ytPlayer && typeof ytPlayer.seekTo === 'function') {
        const startSec = getStartTotalSeconds();
        ytPlayer.seekTo(startSec, true);
        ytPlayer.playVideo();
    }
});

formatSelect.addEventListener('change', () => {
    if (formatSelect.value === 'mp3') {
        qualityGroup.classList.add('hidden');
    } else {
        qualityGroup.classList.remove('hidden');
    }
});

// --- Automatic Download Execution & Task Polling ---
async function startProcessing() {
    const url = ytUrlInput.value.trim();
    if (!url) {
        alert('Please paste a YouTube URL first.');
        return;
    }

    const format = formatSelect.value;
    const quality = qualitySelect.value;
    const is_full_download = (activeMode === 'full-video' || activeMode === 'full-audio');
    const audio_only = (activeMode === 'trim-audio' || activeMode === 'full-audio' || format === 'mp3');

    let start_time = getStartFormatted();
    let end_time = getEndFormatted();

    if (is_full_download) {
        start_time = "00:00:00";
        end_time = videoDurationStr.textContent || "00:00:00";
    } else {
        let startSec = getStartTotalSeconds();
        let endSec = getEndTotalSeconds();
        if (endSec <= startSec) {
            endSec = startSec + 10;
            setEndBoxFromSeconds(endSec);
            end_time = getEndFormatted();
            updateTimelineUI();
        }
    }

    hasAutoDownloaded = false;
    progressModal.classList.remove('hidden');
    downloadResult.classList.add('hidden');
    statusIcon.className = "fa-solid fa-gear fa-spin";
    statusTitle.textContent = is_full_download ? "Downloading Full Media..." : "Processing Clip Segment...";
    progressBarFill.style.width = "10%";
    progressPct.textContent = "10%";
    progressMessage.textContent = "Connecting to downloader engine...";
    etaTimeText.textContent = "~8s remaining";

    try {
        const response = await fetch(getApiUrl('/api/trim'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                start_time,
                end_time,
                format,
                quality,
                audio_only,
                is_full_download
            })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || 'Failed to start processing task');
        }

        const data = await response.json();
        activeTaskId = data.task_id;

        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollTaskStatus, 1000);

    } catch (err) {
        statusIcon.className = "fa-solid fa-triangle-exclamation";
        statusTitle.textContent = "Processing Error";
        progressMessage.textContent = err.message;
        progressBarFill.style.width = "0%";
        progressPct.textContent = "0%";
        etaTimeText.textContent = "Error";
    }
}

async function pollTaskStatus() {
    if (!activeTaskId) return;

    try {
        const response = await fetch(getApiUrl(`/api/status/${activeTaskId}`));
        if (!response.ok) return;

        const data = await response.json();

        progressBarFill.style.width = `${data.progress}%`;
        progressPct.textContent = `${data.progress}%`;
        progressMessage.textContent = data.message;

        if (data.eta_seconds !== undefined && data.eta_seconds > 0) {
            etaTimeText.textContent = `~${data.eta_seconds}s remaining`;
        } else if (data.progress >= 90) {
            etaTimeText.textContent = `~1s remaining`;
        }

        if (data.status === 'completed') {
            clearInterval(pollTimer);
            pollTimer = null;

            statusIcon.className = "fa-solid fa-circle-check";
            statusTitle.textContent = "Media Ready!";
            downloadResult.classList.remove('hidden');
            downloadLinkBtn.href = data.download_url;
            fileSizeLabel.textContent = `${data.file_size_mb} MB`;
            etaTimeText.textContent = "Done!";

            // INSTANT AUTOMATIC FILE DOWNLOAD
            if (!hasAutoDownloaded && data.download_url) {
                hasAutoDownloaded = true;
                const autoLink = document.createElement('a');
                autoLink.href = data.download_url;
                autoLink.download = data.filename || 'clip.mp4';
                document.body.appendChild(autoLink);
                autoLink.click();
                document.body.removeChild(autoLink);
            }

            sendDesktopNotification("ClipTube PRO - Download Ready!", `Your file ${data.filename} (${data.file_size_mb} MB) was automatically downloaded.`);

            fetchHistory();
        } else if (data.status === 'error') {
            clearInterval(pollTimer);
            pollTimer = null;

            statusIcon.className = "fa-solid fa-circle-xmark";
            statusTitle.textContent = "Processing Error";
            progressMessage.textContent = data.message;
            etaTimeText.textContent = "Failed";
        }
    } catch (e) {}
}

// --- History Renderer ---
async function fetchHistory() {
    try {
        const res = await fetch(getApiUrl('/api/history'));
        if (!res.ok) return;
        const data = await res.json();

        if (!data.history || data.history.length === 0) {
            historyList.innerHTML = '<div class="empty-history">No videos or MP3s downloaded yet in this session.</div>';
            return;
        }

        historyList.innerHTML = data.history.map(item => `
            <div class="history-card">
                <div class="history-card-header">
                    <div>
                        <div class="history-title">${item.filename}</div>
                        <span class="history-mode">${item.mode || 'Trimmed'}</span>
                    </div>
                    <div class="history-time">${item.start_time} ➜ ${item.end_time}</div>
                </div>
                <div class="history-card-footer">
                    <span class="history-size">${item.size_mb} MB • ${item.created_at}</span>
                    <a href="${item.download_url}" class="small-dl-btn" download><i class="fa-solid fa-download"></i> Save</a>
                </div>
            </div>
        `).join('');

    } catch (e) {}
}

// --- Event Listeners ---
fetchInfoBtn.addEventListener('click', () => fetchVideoData(ytUrlInput.value));
ytUrlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') fetchVideoData(ytUrlInput.value);
});

clearUrlBtn.addEventListener('click', () => {
    ytUrlInput.value = '';
    ytUrlInput.focus();
});

sampleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        ytUrlInput.value = btn.dataset.url;
        fetchVideoData(btn.dataset.url);
    });
});

startTrimBtn.addEventListener('click', startProcessing);
closeModalBtn.addEventListener('click', () => progressModal.classList.add('hidden'));
refreshHistoryBtn.addEventListener('click', fetchHistory);

// Initial Load Setup
if (getEndTotalSeconds() === 0) {
    setEndBoxFromSeconds(10);
}
applyModeSettings();
fetchHistory();
