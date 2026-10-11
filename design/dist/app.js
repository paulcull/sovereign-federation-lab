'use strict';
document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===document.body.dataset.page));
const toggle=document.getElementById('menu-toggle');if(toggle)toggle.onclick=()=>{const expanded=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!expanded));document.getElementById('sidebar').classList.toggle('open',!expanded);};
document.getElementById('print-page')?.addEventListener('click',()=>window.print());
document.querySelectorAll('.copy-prompt').forEach(button=>button.addEventListener('click',async()=>{const target=document.getElementById(button.dataset.target),status=button.parentElement.querySelector('.copy-status');try{await navigator.clipboard.writeText(target.textContent);status.textContent='Engineering prompt copied.';}catch{target.closest('details').open=true;status.textContent='Select and copy the prompt below.';}}));
