const integrations = [
  { name: 'Webflow', logo: 'W', logoClass: 'webflow', type: 'Website Integration', category: 'Productivity', tone: 'blue', connected: true, description: 'Sync, design, thrive: elevate projects through seamless webflow integration.' },
  { name: 'Whop', logo: '◆', logoClass: 'whop', type: 'E-Commerce Integration', category: 'E-Commerce', tone: 'orange', connected: true, description: 'Here you can sell everything you want (courses, design subscriptions, etc).' },
  { name: 'Dropbox', logo: '◆', logoClass: 'dropbox', type: 'Storage Integration', category: 'Productivity', tone: 'gray', connected: false, description: 'Backup your most essential files to the cloud you can share it with your team.' },
  { name: 'WorkOS', logo: '◈', logoClass: 'workos', type: 'Security Integration', category: 'Productivity', tone: 'indigo', connected: true, description: 'Implement secure and user-friendly SSO experiences by integrating WorkOS.' },
  { name: 'Github', logo: '●', logoClass: 'github', type: 'Management Integration', category: 'Documentation', tone: 'gray', connected: true, description: 'Embrace GitHub integration for effortless project management.' },
  { name: 'Shopify', logo: 'S', logoClass: 'shopify', type: 'E-Commerce Integration', category: 'E-Commerce', tone: 'green', connected: false, description: 'Integrate with shipping and fulfillment services to automate order processing, track shipments.' }
];

const cardGrid = document.querySelector('#cardGrid');
const emptyState = document.querySelector('#emptyState');
const resultCount = document.querySelector('#resultCount');
const searchInput = document.querySelector('#searchInput');
const filterButton = document.querySelector('#filterButton');
const filterCount = document.querySelector('#filterCount');
let currentCategory = 'All integrations';
let connectedOnly = false;

function createCard(item) {
  return `
    <article class="integration-card ${item.tone}" data-name="${item.name.toLowerCase()}">
      <div class="card-top">
        <span class="logo ${item.logoClass}">${item.logo}</span>
        <span class="card-type">▧ ${item.type}</span>
      </div>
      <div class="card-content">
        <h3>${item.name}</h3>
        <p>${item.description}</p>
      </div>
      <div class="card-footer">
        <a href="#" aria-label="View ${item.name} integration">View integration</a>
        <div class="connection">
          <span>${item.connected ? 'Connected' : 'Not Connected'}</span>
          <button class="toggle ${item.connected ? 'on' : ''}" type="button" role="switch" aria-checked="${item.connected}" aria-label="Toggle ${item.name} connection"></button>
        </div>
      </div>
    </article>`;
}

function render() {
  const query = searchInput.value.trim().toLowerCase();
  const visible = integrations.filter(item => {
    const matchesSearch = `${item.name} ${item.type} ${item.description}`.toLowerCase().includes(query);
    const matchesCategory = currentCategory === 'All integrations' || item.category === currentCategory;
    const matchesConnection = !connectedOnly || item.connected;
    return matchesSearch && matchesCategory && matchesConnection;
  });
  cardGrid.innerHTML = visible.map(createCard).join('');
  resultCount.textContent = `(${visible.length})`;
  emptyState.classList.toggle('visible', visible.length === 0);
  filterCount.textContent = connectedOnly ? '1' : '';
  filterButton.classList.toggle('active', connectedOnly);
}

cardGrid.addEventListener('click', event => {
  const toggle = event.target.closest('.toggle');
  if (!toggle) return;
  const card = toggle.closest('.integration-card');
  const item = integrations.find(integration => integration.name.toLowerCase() === card.dataset.name);
  item.connected = !item.connected;
  render();
});

searchInput.addEventListener('input', render);
filterButton.addEventListener('click', () => { connectedOnly = !connectedOnly; render(); });
document.querySelector('#tabs').addEventListener('click', event => {
  const tab = event.target.closest('button');
  if (!tab) return;
  document.querySelectorAll('#tabs button').forEach(button => button.classList.remove('active'));
  tab.classList.add('active');
  currentCategory = tab.dataset.category;
  render();
});

const sidebar = document.querySelector('#sidebar');
document.querySelector('#menuButton').addEventListener('click', () => sidebar.classList.toggle('open'));
document.addEventListener('click', event => {
  if (window.innerWidth <= 760 && sidebar.classList.contains('open') && !sidebar.contains(event.target) && !event.target.closest('#menuButton')) sidebar.classList.remove('open');
});

render();
