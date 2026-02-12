// =======================
// CINEMATIC GIMBAL CONTROL SURFACE
// Pure Vanilla JavaScript
// =======================

// =======================
// STATE MANAGEMENT
// =======================

const state = {
    // Connection
    ws: null,
    wsUrl: 'ws://127.0.0.1:8765',
    connected: false,
    connecting: false,
    
    // Heads
    heads: [],
    selectedHead: -1,
    highlightedHead: 0,
    
    // Invert flags
    invert: {
        yaw: false,
        pitch: false,
        roll: false
    },
    
    // Parameters
    speed: 1.0,
    zoomGain: 60,
    
    // Gamepad axes (semantic)
    axes: {
        X: 0,
        Y: 0,
        Z: 0,
        Xrotate: 0,
        Yrotate: 0,
        Zrotate: 0
    },
    
    // Focus & Navigation
    focusedEncoder: null,
    editingEncoder: null,
    
    // Engineering Mode
    engineeringMode: false,
    rawAxes: [],
    axisMapping: {
        X: 0,
        Y: 1,
        Z: 2,
        Xrotate: 3,
        Yrotate: 4,
        Zrotate: 5
    },
    lastMovedAxis: -1,
    selectedMappingTarget: 0,
    mappingTargets: ['X', 'Y', 'Z', 'Xrotate', 'Yrotate', 'Zrotate'],
    
    // Encoder long-press detection
    encoder5PressStart: null,
    encoder5LongPressThreshold: 2000, // 2 seconds
    
    // Last packet timestamp
    lastPacketTime: null
};

// =======================
// WEBSOCKET
// =======================

function connectWebSocket() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
        console.log('Already connected or connecting');
        return;
    }
    
    state.connecting = true;
    updateConnectionUI();
    
    try {
        state.ws = new WebSocket(state.wsUrl);
        
        state.ws.onopen = () => {
            console.log('WebSocket connected');
            state.connected = true;
            state.connecting = false;
            updateConnectionUI();
        };
        
        state.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                handleIncomingMessage(message);
            } catch (err) {
                console.error('Failed to parse WebSocket message:', err);
            }
        };
        
        state.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
        
        state.ws.onclose = () => {
            console.log('WebSocket disconnected');
            state.connected = false;
            state.connecting = false;
            updateConnectionUI();
        };
    } catch (err) {
        console.error('Failed to connect WebSocket:', err);
        state.connecting = false;
        updateConnectionUI();
    }
}

function disconnectWebSocket() {
    if (state.ws) {
        state.ws.close();
        state.ws = null;
    }
    state.connected = false;
    state.connecting = false;
    updateConnectionUI();
}

function sendWebSocketMessage(message) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(message));
    }
}

function handleIncomingMessage(message) {
    state.lastPacketTime = new Date();
    
    switch (message.type) {
        case 'STATE':
            // Initial state from server
            if (message.heads) {
                state.heads = message.heads;
                updateHeadSelector();
            }
            if (message.selected !== undefined) {
                state.selectedHead = message.selected;
                updateHeadSelector();
                updateHeadInfo();
            }
            if (message.invert) {
                state.invert = message.invert;
                updateInvertToggles();
            }
            if (message.speed !== undefined) {
                state.speed = message.speed;
                updateSpeedUI();
            }
            if (message.zoom_gain !== undefined) {
                state.zoomGain = message.zoom_gain;
                updateZoomGainUI();
            }
            break;
            
        case 'SELECTED':
            // Head selection update
            if (message.selected !== undefined) {
                state.selectedHead = message.selected;
                updateHeadSelector();
                updateHeadInfo();
            }
            break;
    }
    
    updateNetworkInfo();
}

// =======================
// GAMEPAD HANDLING
// =======================

let gamepadIndex = -1;
let previousButtonStates = [];

function pollGamepad() {
    const gamepads = navigator.getGamepads();
    
    // Find first connected gamepad
    if (gamepadIndex === -1) {
        for (let i = 0; i < gamepads.length; i++) {
            if (gamepads[i]) {
                gamepadIndex = i;
                console.log('Gamepad connected:', gamepads[i].id);
                break;
            }
        }
    }
    
    if (gamepadIndex === -1) return;
    
    const gamepad = gamepads[gamepadIndex];
    if (!gamepad) {
        gamepadIndex = -1;
        return;
    }
    
    // Handle axes
    handleGamepadAxes(gamepad);
    
    // Handle buttons (encoder events)
    handleGamepadButtons(gamepad);
}

function handleGamepadAxes(gamepad) {
    // Store raw axes for engineering mode
    state.rawAxes = Array.from(gamepad.axes);
    
    // Detect axis movement for auto-detect
    if (state.engineeringMode) {
        detectMovedAxis();
        updateRawAxesUI();
    }
    
    // Map raw axes to semantic axes using current mapping
    state.axes.X = gamepad.axes[state.axisMapping.X] || 0;
    state.axes.Y = gamepad.axes[state.axisMapping.Y] || 0;
    state.axes.Z = gamepad.axes[state.axisMapping.Z] || 0;
    state.axes.Xrotate = gamepad.axes[state.axisMapping.Xrotate] || 0;
    state.axes.Yrotate = gamepad.axes[state.axisMapping.Yrotate] || 0;
    state.axes.Zrotate = gamepad.axes[state.axisMapping.Zrotate] || 0;
    
    // Update UI
    if (!state.engineeringMode) {
        updateAxisVisualizers();
    }
    
    // Send to server at 20Hz (handled by interval)
}

function handleGamepadButtons(gamepad) {
    // Initialize previous button states if needed
    if (previousButtonStates.length === 0) {
        previousButtonStates = gamepad.buttons.map(b => b.pressed);
        return;
    }
    
    // Detect button press events (transition from false to true)
    for (let i = 0; i < gamepad.buttons.length; i++) {
        const pressed = gamepad.buttons[i].pressed;
        const wasPressed = previousButtonStates[i];
        
        if (pressed && !wasPressed) {
            handleEncoderEvent(i);
        }
        
        previousButtonStates[i] = pressed;
    }
    
    // Handle encoder 5 long-press detection
    if (gamepad.buttons.length > 14 && gamepad.buttons[14].pressed) {
        if (!state.encoder5PressStart) {
            state.encoder5PressStart = Date.now();
        } else {
            const pressDuration = Date.now() - state.encoder5PressStart;
            if (pressDuration >= state.encoder5LongPressThreshold && !state.engineeringMode) {
                // Enter engineering mode
                state.encoder5PressStart = null;
                enterEngineeringMode();
            }
        }
    } else {
        state.encoder5PressStart = null;
    }
}

function handleEncoderEvent(buttonIndex) {
    if (state.engineeringMode) {
        handleEngineeringModeEncoder(buttonIndex);
        return;
    }
    
    // Map button indices to encoder actions
    // Assuming encoders are mapped as:
    // Encoder 1: buttons 0 (CW), 1 (CCW), 2 (Push)
    // Encoder 2: buttons 3 (CW), 4 (CCW), 5 (Push)
    // Encoder 3: buttons 6 (CW), 7 (CCW), 8 (Push)
    // Encoder 4: buttons 9 (CW), 10 (CCW), 11 (Push)
    // Encoder 5: buttons 12 (CW), 13 (CCW), 14 (Push)
    
    const encoderNum = Math.floor(buttonIndex / 3) + 1;
    const action = buttonIndex % 3; // 0=CW, 1=CCW, 2=Push
    
    console.log(`Encoder ${encoderNum}, Action: ${action === 0 ? 'CW' : action === 1 ? 'CCW' : 'Push'}`);
    
    switch (encoderNum) {
        case 1: // HEAD SELECTOR
            if (action === 0) { // CW
                cycleHeadHighlight(1);
            } else if (action === 1) { // CCW
                cycleHeadHighlight(-1);
            } else if (action === 2) { // Push
                selectHighlightedHead();
            }
            break;
            
        case 2: // SPEED
            if (action === 0) { // CW
                adjustSpeed(0.1);
            } else if (action === 1) { // CCW
                adjustSpeed(-0.1);
            } else if (action === 2) { // Push
                // Toggle fine/coarse (not implemented yet)
                toggleEncoderFocus(2);
            }
            break;
            
        case 3: // ZOOM GAIN
            if (action === 0) { // CW
                adjustZoomGain(5);
            } else if (action === 1) { // CCW
                adjustZoomGain(-5);
            } else if (action === 2) { // Push
                // Toggle fine/coarse (not implemented yet)
                toggleEncoderFocus(3);
            }
            break;
            
        case 4: // MENU/NAV
            if (action === 0) { // CW
                moveFocus(1);
            } else if (action === 1) { // CCW
                moveFocus(-1);
            } else if (action === 2) { // Push
                toggleConnectionOverlay();
            }
            break;
            
        case 5: // CONFIRM/BACK
            if (action === 0) { // CW
                // Optional quick actions
            } else if (action === 1) { // CCW
                // Optional quick actions
            } else if (action === 2) { // Push (short press, long press handled separately)
                confirmAction();
            }
            break;
    }
}

function handleEngineeringModeEncoder(buttonIndex) {
    const encoderNum = Math.floor(buttonIndex / 3) + 1;
    const action = buttonIndex % 3;
    
    switch (encoderNum) {
        case 1: // Scroll raw axes list (not implemented, list is short enough)
            break;
            
        case 4: // Navigate mapping targets
            if (action === 0) { // CW
                state.selectedMappingTarget = (state.selectedMappingTarget + 1) % state.mappingTargets.length;
                updateMappingUI();
            } else if (action === 1) { // CCW
                state.selectedMappingTarget = (state.selectedMappingTarget - 1 + state.mappingTargets.length) % state.mappingTargets.length;
                updateMappingUI();
            }
            break;
            
        case 5: // Assign detected axis to selected target
            if (action === 2 && state.lastMovedAxis !== -1) { // Push
                const target = state.mappingTargets[state.selectedMappingTarget];
                state.axisMapping[target] = state.lastMovedAxis;
                updateMappingUI();
                console.log(`Mapped ${target} to raw axis ${state.lastMovedAxis}`);
            }
            break;
    }
}

// =======================
// ENCODER ACTIONS
// =======================

function cycleHeadHighlight(direction) {
    if (state.heads.length === 0) return;
    state.highlightedHead = (state.highlightedHead + direction + state.heads.length) % state.heads.length;
    updateHeadSelector();
}

function selectHighlightedHead() {
    if (state.heads.length === 0) return;
    sendWebSocketMessage({
        type: 'SELECT_HEAD',
        index: state.highlightedHead
    });
}

function adjustSpeed(delta) {
    state.speed = Math.max(0.2, Math.min(2.0, state.speed + delta));
    state.speed = Math.round(state.speed * 10) / 10; // Round to 1 decimal
    updateSpeedUI();
    sendWebSocketMessage({
        type: 'SET_SPEED',
        speed: state.speed
    });
}

function adjustZoomGain(delta) {
    state.zoomGain = Math.max(10, Math.min(150, state.zoomGain + delta));
    updateZoomGainUI();
    sendWebSocketMessage({
        type: 'SET_ZOOM_GAIN',
        zoom_gain: state.zoomGain
    });
}

function toggleEncoderFocus(encoderNum) {
    if (state.focusedEncoder === encoderNum) {
        state.focusedEncoder = null;
    } else {
        state.focusedEncoder = encoderNum;
    }
    updateEncoderFocus();
}

function moveFocus(direction) {
    // Cycle through focusable encoders
    const focusableEncoders = [1, 2, 3, 4, 5];
    let currentIndex = focusableEncoders.indexOf(state.focusedEncoder);
    if (currentIndex === -1) currentIndex = 0;
    
    const newIndex = (currentIndex + direction + focusableEncoders.length) % focusableEncoders.length;
    state.focusedEncoder = focusableEncoders[newIndex];
    updateEncoderFocus();
}

function confirmAction() {
    // Context-dependent confirm action
    console.log('Confirm pressed');
}

function toggleConnectionOverlay() {
    const overlay = document.getElementById('connectionOverlay');
    overlay.classList.toggle('active');
}

// =======================
// INVERT TOGGLES
// =======================

function toggleInvert(axis) {
    state.invert[axis] = !state.invert[axis];
    updateInvertToggles();
    sendWebSocketMessage({
        type: 'SET_INVERT',
        invert: state.invert
    });
}

// =======================
// ENGINEERING MODE
// =======================

function enterEngineeringMode() {
    state.engineeringMode = true;
    document.getElementById('operatorMode').classList.add('hidden');
    document.getElementById('engineeringMode').classList.remove('hidden');
    loadAxisMapping();
    updateMappingUI();
}

function exitEngineeringMode() {
    state.engineeringMode = false;
    document.getElementById('engineeringMode').classList.add('hidden');
    document.getElementById('operatorMode').classList.remove('hidden');
}

function detectMovedAxis() {
    // Find axis with largest absolute value or recent change
    let maxChange = 0;
    let maxIndex = -1;
    
    for (let i = 0; i < state.rawAxes.length; i++) {
        const absValue = Math.abs(state.rawAxes[i]);
        if (absValue > 0.1 && absValue > maxChange) {
            maxChange = absValue;
            maxIndex = i;
        }
    }
    
    if (maxIndex !== -1) {
        state.lastMovedAxis = maxIndex;
    }
}

function resetAxisMapping() {
    state.axisMapping = {
        X: 0,
        Y: 1,
        Z: 2,
        Xrotate: 3,
        Yrotate: 4,
        Zrotate: 5
    };
    saveAxisMapping();
    updateMappingUI();
}

function saveAxisMapping() {
    localStorage.setItem('axisMapping', JSON.stringify(state.axisMapping));
    console.log('Axis mapping saved');
}

function loadAxisMapping() {
    const saved = localStorage.getItem('axisMapping');
    if (saved) {
        try {
            state.axisMapping = JSON.parse(saved);
            console.log('Axis mapping loaded');
        } catch (err) {
            console.error('Failed to load axis mapping:', err);
        }
    }
}

// =======================
// UI UPDATES
// =======================

function updateConnectionUI() {
    const statusDot = document.getElementById('statusDot');
    const statusLabel = document.getElementById('statusLabel');
    
    statusDot.classList.remove('connecting', 'connected');
    
    if (state.connecting) {
        statusDot.classList.add('connecting');
        statusLabel.textContent = 'CONNECTING';
    } else if (state.connected) {
        statusDot.classList.add('connected');
        statusLabel.textContent = 'CONNECTED';
    } else {
        statusLabel.textContent = 'DISCONNECTED';
    }
}

function updateHeadInfo() {
    const headName = document.getElementById('headName');
    const headIP = document.getElementById('headIP');
    
    if (state.selectedHead >= 0 && state.selectedHead < state.heads.length) {
        const head = state.heads[state.selectedHead];
        headName.textContent = head.name;
        headIP.textContent = `${head.ip}:${head.port}`;
    } else {
        headName.textContent = 'NO HEAD';
        headIP.textContent = '—';
    }
}

function updateHeadSelector() {
    const headList = document.getElementById('headList');
    headList.innerHTML = '';
    
    if (state.heads.length === 0) {
        const item = document.createElement('div');
        item.className = 'head-item';
        item.textContent = 'NO HEADS';
        headList.appendChild(item);
        return;
    }
    
    state.heads.forEach((head, index) => {
        const item = document.createElement('div');
        item.className = 'head-item';
        if (index === state.selectedHead) {
            item.classList.add('selected');
        }
        if (index === state.highlightedHead) {
            item.classList.add('highlighted');
        }
        item.textContent = head.name;
        headList.appendChild(item);
    });
}

function updateSpeedUI() {
    const speedDisplay = document.getElementById('speedDisplay');
    const speedSlider = document.getElementById('speedSlider');
    const encoder2Value = document.querySelector('#encoder2 .slider-text');
    
    const speedText = state.speed.toFixed(1) + '×';
    speedDisplay.textContent = speedText;
    encoder2Value.textContent = speedText;
    
    // Calculate slider fill (0.2 to 2.0 maps to 0% to 100%)
    const percentage = ((state.speed - 0.2) / (2.0 - 0.2)) * 100;
    speedSlider.style.width = percentage + '%';
}

function updateZoomGainUI() {
    const zoomGainDisplay = document.getElementById('zoomGainDisplay');
    const zoomGainSlider = document.getElementById('zoomGainSlider');
    const encoder3Value = document.querySelector('#encoder3 .slider-text');
    
    const zoomText = state.zoomGain.toString();
    zoomGainDisplay.textContent = zoomText;
    encoder3Value.textContent = zoomText;
    
    // Calculate slider fill (10 to 150 maps to 0% to 100%)
    const percentage = ((state.zoomGain - 10) / (150 - 10)) * 100;
    zoomGainSlider.style.width = percentage + '%';
}

function updateInvertToggles() {
    document.getElementById('invertYaw').classList.toggle('active', state.invert.yaw);
    document.getElementById('invertPitch').classList.toggle('active', state.invert.pitch);
    document.getElementById('invertRoll').classList.toggle('active', state.invert.roll);
}

function updateAxisVisualizers() {
    // PAN (X axis)
    updateGaugeFill('panFill', state.axes.X);
    document.getElementById('panValue').textContent = state.axes.X.toFixed(1);
    
    // TILT (Y axis)
    updateGaugeFill('tiltFill', state.axes.Y);
    document.getElementById('tiltValue').textContent = state.axes.Y.toFixed(1);
    
    // ROLL (Z axis)
    updateGaugeFill('rollFill', state.axes.Z);
    document.getElementById('rollValue').textContent = state.axes.Z.toFixed(1);
    
    // ZOOM (Zrotate)
    updateLensFill('zoomFill', state.axes.Zrotate);
    document.getElementById('zoomValue').textContent = state.axes.Zrotate.toFixed(1);
    
    // FOCUS (Xrotate)
    updateLensFill('focusFill', state.axes.Xrotate);
    document.getElementById('focusValue').textContent = state.axes.Xrotate.toFixed(1);
    
    // IRIS (Yrotate)
    updateLensFill('irisFill', state.axes.Yrotate);
    document.getElementById('irisValue').textContent = state.axes.Yrotate.toFixed(1);
}

function updateGaugeFill(elementId, value) {
    // Gauge fill for centered axis (-1 to 1)
    const element = document.getElementById(elementId);
    const percentage = Math.abs(value) * 50; // 0 to 50%
    
    element.style.width = percentage + '%';
    
    if (value >= 0) {
        element.style.left = '50%';
    } else {
        element.style.left = (50 - percentage) + '%';
    }
}

function updateLensFill(elementId, value) {
    // Lens fill for unidirectional axis (-1 to 1, displayed as 0 to 100%)
    const element = document.getElementById(elementId);
    const percentage = ((value + 1) / 2) * 100; // Map -1..1 to 0..100%
    element.style.width = percentage + '%';
}

function updateEncoderFocus() {
    // Update visual focus states
    document.querySelectorAll('.encoder-zone').forEach((zone, index) => {
        const encoderNum = index + 1;
        zone.classList.toggle('focused', state.focusedEncoder === encoderNum);
        zone.classList.toggle('editing', state.editingEncoder === encoderNum);
    });
}

function updateNetworkInfo() {
    const networkInfo = document.getElementById('networkInfo');
    if (state.lastPacketTime) {
        const elapsed = Date.now() - state.lastPacketTime;
        if (elapsed < 1000) {
            networkInfo.querySelector('.last-packet').textContent = 'LIVE';
        } else {
            networkInfo.querySelector('.last-packet').textContent = `${Math.floor(elapsed / 1000)}s ago`;
        }
    } else {
        networkInfo.querySelector('.last-packet').textContent = '—';
    }
}

// Engineering Mode UI

function updateRawAxesUI() {
    const rawAxesContainer = document.getElementById('rawAxes');
    rawAxesContainer.innerHTML = '';
    
    state.rawAxes.forEach((value, index) => {
        const axisDiv = document.createElement('div');
        axisDiv.className = 'raw-axis';
        if (index === state.lastMovedAxis) {
            axisDiv.classList.add('moved');
        }
        
        const label = document.createElement('span');
        label.className = 'raw-axis-label';
        label.textContent = `AXIS ${index}`;
        
        const barContainer = document.createElement('div');
        barContainer.className = 'raw-axis-bar';
        
        const fill = document.createElement('div');
        fill.className = 'raw-axis-fill';
        const percentage = Math.abs(value) * 50;
        fill.style.width = percentage + '%';
        if (value >= 0) {
            fill.style.left = '50%';
        } else {
            fill.style.left = (50 - percentage) + '%';
        }
        
        barContainer.appendChild(fill);
        
        const valueSpan = document.createElement('span');
        valueSpan.className = 'raw-axis-value';
        valueSpan.textContent = value.toFixed(2);
        
        axisDiv.appendChild(label);
        axisDiv.appendChild(barContainer);
        axisDiv.appendChild(valueSpan);
        
        rawAxesContainer.appendChild(axisDiv);
    });
    
    // Update last moved indicator
    document.getElementById('lastMovedAxis').textContent = 
        state.lastMovedAxis === -1 ? '—' : `AXIS ${state.lastMovedAxis}`;
}

function updateMappingUI() {
    // Highlight selected mapping target
    document.querySelectorAll('.mapping-row').forEach((row, index) => {
        row.classList.toggle('selected', index === state.selectedMappingTarget);
    });
    
    // Update mapping sources
    Object.keys(state.axisMapping).forEach(target => {
        const element = document.getElementById('map' + target);
        if (element) {
            element.textContent = `AXIS ${state.axisMapping[target]}`;
        }
    });
}

// =======================
// EVENT LISTENERS
// =======================

document.addEventListener('DOMContentLoaded', () => {
    // Connection overlay
    document.getElementById('connectBtn').addEventListener('click', () => {
        state.wsUrl = document.getElementById('wsUrl').value;
        connectWebSocket();
    });
    
    document.getElementById('disconnectBtn').addEventListener('click', () => {
        disconnectWebSocket();
    });
    
    document.getElementById('closeOverlay').addEventListener('click', () => {
        toggleConnectionOverlay();
    });
    
    // Invert toggles
    document.getElementById('invertYaw').addEventListener('click', () => toggleInvert('yaw'));
    document.getElementById('invertPitch').addEventListener('click', () => toggleInvert('pitch'));
    document.getElementById('invertRoll').addEventListener('click', () => toggleInvert('roll'));
    
    // Encoder zones (touch support)
    document.querySelectorAll('.encoder-zone').forEach((zone, index) => {
        zone.addEventListener('click', () => {
            const encoderNum = index + 1;
            state.focusedEncoder = encoderNum;
            updateEncoderFocus();
        });
    });
    
    // Engineering mode
    document.getElementById('resetMapping').addEventListener('click', () => {
        if (confirm('Reset axis mapping to default?')) {
            resetAxisMapping();
        }
    });
    
    document.getElementById('saveMapping').addEventListener('click', () => {
        saveAxisMapping();
        alert('Mapping saved!');
    });
    
    document.getElementById('exitEngineering').addEventListener('click', () => {
        exitEngineeringMode();
    });
    
    // Easter egg: tap top-left corner 5 times to enter engineering mode
    let tapCount = 0;
    let tapTimer = null;
    document.querySelector('.status-bar').addEventListener('click', (e) => {
        if (e.clientX < 100 && e.clientY < 60 && !state.engineeringMode) {
            tapCount++;
            clearTimeout(tapTimer);
            tapTimer = setTimeout(() => {
                tapCount = 0;
            }, 2000);
            
            if (tapCount === 5) {
                tapCount = 0;
                enterEngineeringMode();
            }
        }
    });
    
    // Load saved axis mapping
    loadAxisMapping();
    
    // Initialize UI
    updateConnectionUI();
    updateHeadInfo();
    updateSpeedUI();
    updateZoomGainUI();
    updateInvertToggles();
    updateEncoderFocus();
});

// =======================
// MAIN LOOPS
// =======================

// Gamepad polling (60 Hz)
setInterval(() => {
    pollGamepad();
}, 1000 / 60);

// Send gamepad data to server (20 Hz)
setInterval(() => {
    if (state.connected && !state.engineeringMode) {
        sendWebSocketMessage({
            type: 'GAMEPAD',
            axes: state.axes
        });
    }
}, 1000 / 20);

// Update network info display
setInterval(() => {
    updateNetworkInfo();
}, 1000);

// =======================
// GAMEPAD CONNECTION EVENTS
// =======================

window.addEventListener('gamepadconnected', (e) => {
    console.log('Gamepad connected:', e.gamepad.id);
    gamepadIndex = e.gamepad.index;
});

window.addEventListener('gamepaddisconnected', (e) => {
    console.log('Gamepad disconnected:', e.gamepad.id);
    if (e.gamepad.index === gamepadIndex) {
        gamepadIndex = -1;
    }
});

// =======================
// STARTUP
// =======================

console.log('Cinematic Gimbal Control Surface initialized');
console.log('Waiting for gamepad connection...');
