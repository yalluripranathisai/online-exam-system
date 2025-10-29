// helper used in add_question template (keeps checkbox value in sync with option text)
function syncOptionCheckboxes() {
  document.querySelectorAll('.option-row').forEach(function(row) {
    var input = row.querySelector('.option-input');
    var cb = row.querySelector('.option-cb');
    if (!input || !cb) return;
    // set initial
    cb.value = input.value;
    // keep in sync
    input.addEventListener('input', function() {
      cb.value = input.value;
    });
  });
}

document.addEventListener('DOMContentLoaded', function() {
  syncOptionCheckboxes();
  // add-option button behavior (if present)
  var addBtn = document.getElementById('add-option-btn');
  if (addBtn) {
    addBtn.addEventListener('click', function(e) {
      e.preventDefault();
      var container = document.getElementById('options-container');
      var newRow = document.createElement('div');
      newRow.className = 'option-row';
      newRow.innerHTML = '<input name="option" class="option-input" placeholder="Option text"> <label><input type="checkbox" name="correct" class="option-cb"> Correct</label>';
      container.appendChild(newRow);
      syncOptionCheckboxes();
    });
  }

  // show/hide fields based on qtype select (if present)
  var qtype = document.getElementById('qtype-select');
  if (qtype) {
    qtype.addEventListener('change', function(e) {
      var val = e.target.value;
      var mcqArea = document.getElementById('mcq-area');
      var expectedArea = document.getElementById('expected-area');
      if (val.startsWith('mcq')) {
        mcqArea.style.display = 'block';
        expectedArea.style.display = 'none';
      } else {
        mcqArea.style.display = 'none';
        expectedArea.style.display = 'block';
      }
    });
  }
});
