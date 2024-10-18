function showSettingsModal() {
    document.getElementById('settingsModal').classList.remove('hidden');
}

function closeSettingsModal() {
    document.getElementById('settingsModal').classList.add('hidden');
}

// Expose functions to the global scope
window.showSettingsModal = showSettingsModal;
window.closeSettingsModal = closeSettingsModal;