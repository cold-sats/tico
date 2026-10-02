const form = document.querySelector('form');
const address = document.querySelector('#address');
const error = document.querySelector('#error');
const button = document.querySelector('button');
const invoke = window.__TAURI__.core.invoke;
invoke('server_address').then(value => { address.value = value; }).catch(() => {});
form.addEventListener('submit', async event => {
  event.preventDefault();
  error.textContent = '';
  button.disabled = true;
  button.textContent = 'Connecting…';
  try {
    await invoke('connect_server', { address: address.value });
  } catch (message) {
    error.textContent = String(message);
  } finally {
    button.disabled = false;
    button.textContent = 'Connect';
  }
});
