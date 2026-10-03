document.querySelectorAll(".like").forEach(btn=>{
  btn.addEventListener("click", async ()=>{
    const id=btn.dataset.id;
    const r=await fetch(`/like/${id}`,{method:"POST"});
    if(r.ok){const data=await r.json();btn.querySelector("span").textContent=data.likes;btn.disabled=true;}
  });
});