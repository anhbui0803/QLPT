document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('searchForm');
    const results = document.getElementById('searchResults');
    if (!form || !results) return;
  
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const data = {
        district: form.district.value,
        price:    form.price.value,
        type:     form.type.value,
      };
      try {
        const res = await fetch('/api/search', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(data),
        });
        const json = await res.json();
        // clear and render
        results.innerHTML = '';
        json.data.forEach(m => {
          const col = document.createElement('div');
          col.className = 'col-md-4 mb-4';
          col.innerHTML = `
            <div class="card motel-card">
              <div class="position-relative">
                <img src="${m.image}" class="card-img-top">
                <span class="district-badge">${m.district}</span>
              </div>
              <div class="card-body">
                <h5 class="card-title">${m.title}</h5>
                <p class="card-text">${m.description}</p>
                <div class="amenities mb-2">
                  ${m.amenities.map(a=>`<span>${a}</span>`).join('')}
                </div>
                <div class="d-flex justify-content-between">
                  <span class="price-tag">${m.price}k/tháng</span>
                  <small>${m.area}m²</small>
                </div>
                <a href="${m.url}" class="btn btn-outline-primary w-100 mt-3">Xem Chi Tiết</a>
              </div>
            </div>`;
          results.append(col);
        });
      } catch(err) {
        console.error('Search failed', err);
      }
    });
  });