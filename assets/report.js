(function () {
  var search = document.getElementById('search');
  var sort = document.getElementById('sort');
  var container = document.getElementById('candidates');
  if (!container) return;
  if (search) search.addEventListener('input', function () {
    var needle = search.value.trim().toLowerCase();
    Array.prototype.forEach.call(container.children, function (card) {
      card.hidden = needle && card.dataset.title.toLowerCase().indexOf(needle) === -1;
    });
  });
  if (!sort) return;
  var ranked = true;
  sort.addEventListener('click', function () {
    var cards = Array.prototype.slice.call(container.children);
    if (ranked) {
      cards.sort(function (left, right) { return Number(left.dataset.index) - Number(right.dataset.index); });
      sort.textContent = '切换排名顺序';
    } else {
      cards.sort(function (left, right) {
        var leftRank = Number(left.dataset.rank) || 9999;
        var rightRank = Number(right.dataset.rank) || 9999;
        if (leftRank !== rightRank) return leftRank - rightRank;
        return Number(left.dataset.index) - Number(right.dataset.index);
      });
      sort.textContent = '切换原始顺序';
    }
    cards.forEach(function (card) { container.appendChild(card); });
    ranked = !ranked;
  });
}());

