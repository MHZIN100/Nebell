(()=>{
const $=s=>document.querySelector(s), cv=$('#hud');
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
// O nucleo e a nuvem de particulas: cada forma e um estado, e o
// mapa das ferramentas sai do proprio nebell.py.
const nucleo=NebellFormas.criar(cv,{particulas:30000});
let demo=true;

// Para o fundo da janela mudar de cor junto com o estado.
const FAMILIA={espera:'idle',ouvindo:'listening',pensando:'thinking',
 falando:'speaking',alerta:'alerta',erro:'alerta',encerrando:'idle'};

function bridge(){return window.pywebview&&window.pywebview.api?window.pywebview.api:null}

function setState(s){
 if(!nucleo.setState(s))return;
 const n=nucleo.numeros;
 $('#state').textContent=n.rotulo;
 $('#sub').textContent=n.diz;
 document.body.dataset.state=FAMILIA[n.estado]||'trabalhando'}
function addMessage(role,text){fecharStream();const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'nebell');
 const t=new Date().toLocaleTimeString('pt-BR');const sm=document.createElement('small');sm.textContent=(role==='user'?'VOCÊ':'NEBELL')+' · '+t;
 const p=document.createElement('div');p.textContent=text;d.append(sm,p);const log=$('#log');log.append(d);
 while(log.children.length>60)log.firstChild.remove();log.scrollTop=log.scrollHeight}

// Bolha que se preenche enquanto ele gera. Antes o texto so aparecia
// no fim, depois de ele terminar de falar: quem olhava a janela nao
// sabia se tinha algo acontecendo.
let streamP=null;
function streamMessage(text){
 const log=$('#log');
 if(!streamP){
  const d=document.createElement('div');d.className='msg nebell streaming';
  const t=new Date().toLocaleTimeString('pt-BR');
  const sm=document.createElement('small');sm.textContent='NEBELL · '+t;
  streamP=document.createElement('div');
  d.append(sm,streamP);log.append(d);
  while(log.children.length>60)log.firstChild.remove();
 }
 streamP.textContent=text;
 log.scrollTop=log.scrollHeight}
function fecharStream(){
 if(streamP){const d=streamP.parentElement;if(d)d.classList.remove('streaming');streamP=null}}
function trabalhando(text){
 const el=$('#work');
 if(!el)return;
 if(text){el.textContent=text;el.classList.add('on')}
 else{el.textContent='';el.classList.remove('on')}}
function setStats(o){for(const k of['cpu','ram','net','gpu']){if(o[k]==null)continue;const v=Math.max(0,Math.min(100,o[k]));
 $('#'+k).style.width=v+'%';
 const rotulo=o[k+'Label'];$('#'+k+'V').textContent=rotulo||Math.round(v)+'%'}
 if(o.netLabel&&o.net==null)$('#netV').textContent=o.netLabel;
 if(o.gpuLabel&&o.gpu==null)$('#gpuV').textContent=o.gpuLabel;
 if(o.model)$('#mdl').textContent=o.model;
 if(o.voice)$('#voz').textContent=o.voice;
 if(o.stt)$('#stt').textContent=o.stt;
 if(o.mic)$('#micV').textContent=o.mic;
 if(o.location)$('#loc').textContent=o.location}
function setMics(list,current){const sel=$('#mic');if(!Array.isArray(list))return;
 sel.textContent='';const auto=document.createElement('option');auto.value='auto';auto.textContent='MICROFONE: AUTOMÁTICO';sel.append(auto);
 for(const d of list){const o=document.createElement('option');o.value=String(d.index);
  o.textContent=(d.is_headset?'FONE · ':'')+(d.name||('entrada '+d.index));sel.append(o)}
 if(current!=null)sel.value=String(current);atualizarTituloMic()}
// Sem rotulo visivel, o nome do microfone vive no tooltip do icone.
function atualizarTituloMic(){const sel=$('#mic'),btn=$('#micbtn');if(!sel||!btn)return;
 const op=sel.options[sel.selectedIndex];const t=op?op.textContent:'';
 btn.title=t?('Microfone: '+t):'Microfone de entrada'}
// Seletor de voz: o Python manda a lista (só as vozes que funcionam
// nesta máquina) e qual está em uso. Trocar aqui muda a voz na hora.
function setVozes(list,atual){const sel=$('#vozSel');if(!sel||!Array.isArray(list))return;
 sel.textContent='';
 for(const v of list){const o=document.createElement('option');o.value=v.chave||'';o.textContent=v.rotulo||v.chave||'voz';sel.append(o)}
 if(atual!=null&&atual!=='')sel.value=String(atual);}
function setVozAtual(ch){const sel=$('#vozSel');if(sel&&ch!=null&&ch!=='')sel.value=String(ch)}
// Botão de silenciar o microfone. O Python é quem manda o estado de
// verdade (inclusive na abertura), então o visual segue o aria-pressed.
function setMudo(on){const b=$('#micmute');if(!b)return;
 b.setAttribute('aria-pressed',on?'true':'false');
 b.title=on?'Microfone silenciado — clique para religar':'Silenciar o microfone';}
function submit(text){text=text.trim();if(!text)return;addMessage('user',text);
 const b=bridge();
 if(b&&b.send){demo=false;setState('pensando');b.send(text)}
 else if(api.onSubmit)api.onSubmit(text);
 else{setState('pensando');setTimeout(()=>{setState('falando');addMessage('nebell','Modo demonstração, senhor. Estou pronto para ser conectado.');setTimeout(()=>setState('espera'),2200)},1100)}}
const api={
 setState:s=>{demo=false;setState(s)},
 // O Python manda o NOME DA FERRAMENTA que esta rodando; a forma
 // sai do mapa que ja existe no nebell.py.
 paraFerramenta:nome=>{demo=false;
  if(nucleo.paraFerramenta(nome)){const n=nucleo.numeros;
   $('#state').textContent=n.rotulo;$('#sub').textContent=n.diz;
   document.body.dataset.state=FAMILIA[n.estado]||'trabalhando'}},
 setEsforco:v=>nucleo.setEsforco(v),
 setEsforcoNivel:n=>aplicarEsforco(String(n),false),
 setLevel:v=>nucleo.setLevel(v),
 addMessage,streamMessage,fecharStream,trabalhando,setStats,setMics,
 setVozes,setVozAtual,setMudo,
 onSubmit:null,setDemo:v=>{demo=!!v}};
window.nebellUI=api;


// relógio e estatísticas simuladas (o Python substitui via setStats)
const days=['DOMINGO','SEGUNDA','TERÇA','QUARTA','QUINTA','SEXTA','SÁBADO'];
function tick(){const n=new Date();$('#clk').textContent=n.toLocaleTimeString('pt-BR');$('#dt').textContent=days[n.getDay()]+' · '+n.toLocaleDateString('pt-BR')}
tick();setInterval(tick,1000);
let fake=true;const _s=setStats;
// O ESFORCO da nuvem nao e inventado: sai da CPU e da placa que o
// Python ja manda para o painel. Penando, ela ferve.
function daCarga(o){
 const cpu=typeof o.cpu==='number'?o.cpu:null;
 const gpu=typeof o.gpu==='number'?o.gpu:null;
 if(cpu==null&&gpu==null)return;
 const pior=Math.max(cpu==null?0:cpu,gpu==null?0:gpu);
 nucleo.setEsforco(Math.max(0,Math.min(1,(pior-35)/55)))}
api.setStats=o=>{fake=false;_s(o);daCarga(o)};
setInterval(()=>{if(fake)_s({cpu:15+Math.random()*40,ram:45+Math.random()*10,gpu:5+Math.random()*50,net:10+Math.random()*60,netLabel:'24 ms'})},1500);

// controles
$('#txt').addEventListener('keydown',e=>{if(e.key==='Enter'){submit(e.target.value);e.target.value=''}});
$('#mic').addEventListener('change',e=>{atualizarTituloMic();const b=bridge();if(b&&b.set_mic)b.set_mic(e.target.value)});
// Trocar a voz pelo seletor do painel SISTEMA.
$('#vozSel').addEventListener('change',e=>{const v=e.target.value;if(!v)return;const b=bridge();if(b&&b.set_voz)b.set_voz(v)});
// Silenciar / religar o microfone. Lê o estado atual do próprio botão
// e inverte, para ficar sempre em sincronia com o que o Python mandou.
$('#micmute').addEventListener('click',()=>{const b=$('#micmute');const novo=b.getAttribute('aria-pressed')!=='true';setMudo(novo);const br=bridge();if(br&&br.set_mudo)br.set_mudo(novo)});
$('#halt').addEventListener('click',()=>{const b=bridge();if(b&&b.stop)b.stop()});
// O seletor e o NATIVO, do lado do Python: o <input type=file> do HTML
// nao entrega o caminho no disco, e sem caminho o NEBELL nao consegue
// editar o arquivo depois.
$('#file').addEventListener('click',async()=>{
 const b=bridge(),bt=$('#file');
 if(!b||!b.pick_files){addMessage('nebell','O seletor de arquivos só funciona na janela do NEBELL, senhor.');return}
 bt.disabled=true;
 try{
  const caminhos=await b.pick_files();
  if(caminhos&&caminhos.length){
   const nomes=caminhos.map(c=>String(c).split(/[\\/]/).pop());
   addMessage('user','Enviei: '+nomes.join(', '));
   setState('pensando');
  }
 }catch(e){addMessage('nebell','Não consegui abrir o seletor: '+e)}
 finally{bt.disabled=false}});
// Botao ESFORCO: rapido -> normal -> alto -> rapido. Este e o unico
// lugar que liga o "pensar antes de responder" do modelo (nivel alto).
const NIVEIS_ESFORCO=['rapido','normal','alto'];
const ROTULO_ESFORCO={rapido:'Instantânea',normal:'Média',alto:'Alta'};
let nivelEsforco='normal';

// Elementos da pista horizontal.
const efTrack=$('#ef-track'),efBall=$('#ef-ball'),efFill=$('#ef-fill'),
      efCv=$('#ef-canvas'),efNome=$('#ep-nome'),efPop=$('#effort-pop');
const EF_PONTOS={rapido:0,normal:0.5,alto:1};   // 0=esquerda, 1=direita (cheio)
const EF_R=11;                                  // raio da bolinha (px)
const EF_NOMES={rapido:'INSTANTÂNEA',normal:'MÉDIA',alto:'ALTA'};
let efCtx=efCv?efCv.getContext('2d'):null,efW=1,efH=1,efRaf=0,efArr=false,
    efBolhas=[],efMeteoros=[],efEstrelas=[];

function pintarEsforco(){const bt=$('#effort');if(bt){
  bt.dataset.nivel=nivelEsforco;
  bt.title='Esforço: '+(ROTULO_ESFORCO[nivelEsforco]||nivelEsforco)+'. Clique para abrir a barra.';}
 pintarPopover();}
function pintarPopover(){
 if(efPop)efPop.dataset.nivel=nivelEsforco;
 if(efTrack)efTrack.dataset.nivel=nivelEsforco;
 if(efNome)efNome.textContent=EF_NOMES[nivelEsforco]||nivelEsforco;
 if(!efArr)efPos(EF_PONTOS[nivelEsforco]!=null?EF_PONTOS[nivelEsforco]:0.5);}
function aplicarEsforco(nivel,avisarPython){
 if(NIVEIS_ESFORCO.indexOf(nivel)<0)return;
 const mudou=nivel!==nivelEsforco;
 nivelEsforco=nivel;pintarEsforco();
 if(avisarPython&&mudou){const b=bridge();if(b&&b.set_esforco)b.set_esforco(nivel);}}
function abrirEsforco(abrir){const pop=$('#effort-pop');if(pop)pop.hidden=!abrir;
 ligarEsforcoAnim(!!abrir);if(abrir)pintarPopover();}  // repinta com a largura já visível

// --- bolinha e preenchimento ---
// Posiciona em pixels levando o raio da bolinha em conta: assim no 0 ela
// fica colada na esquerda e no 1 colada na direita (sem vazar), e o
// preenchimento vai até a borda direita dela — no Alta a barra enche 100%.
function efPos(frac){if(!efTrack)return;
 const w=efTrack.clientWidth; if(!w)return;
 const cx=EF_R+frac*(w-2*EF_R);
 if(efBall)efBall.style.left=cx+'px';
 if(efFill)efFill.style.width=Math.min(w,cx+EF_R)+'px';}
function efMedir(){if(!efTrack||!efCv)return;const r=efTrack.getBoundingClientRect();
 efW=efCv.width=Math.max(1,Math.round(r.width));efH=efCv.height=Math.max(1,Math.round(r.height));
 efCv.style.width=efW+'px';efCv.style.height=efH+'px';
 efEstrelas=Array.from({length:36},()=>({x:Math.random()*efW,y:Math.random()*efH,r:Math.random()*1.1+0.3,f:Math.random()*6.28}));}

// --- as três cenas animadas ---
function efCena(t){if(!efCtx)return;efCtx.clearRect(0,0,efW,efH);
 if(nivelEsforco==='rapido'){                       // azul calmo
  const g=efCtx.createLinearGradient(0,0,efW,0);g.addColorStop(0,'#123a6b');g.addColorStop(1,'#2f7bd6');
  efCtx.fillStyle=g;efCtx.fillRect(0,0,efW,efH);
  const x=((t/1500)%1)*efW;const gg=efCtx.createLinearGradient(x-40,0,x+40,0);
  gg.addColorStop(0,'rgba(255,255,255,0)');gg.addColorStop(.5,'rgba(255,255,255,.16)');gg.addColorStop(1,'rgba(255,255,255,0)');
  efCtx.fillStyle=gg;efCtx.fillRect(0,0,efW,efH);
 }else if(nivelEsforco==='normal'){                 // laranja borbulhando
  const g=efCtx.createLinearGradient(0,0,0,efH);g.addColorStop(0,'#c8541a');g.addColorStop(1,'#eb922c');
  efCtx.fillStyle=g;efCtx.fillRect(0,0,efW,efH);
  if(Math.random()<0.32)efBolhas.push({x:Math.random()*efW,y:efH+4,r:Math.random()*3+1.5,v:Math.random()*0.6+0.4,w:Math.random()*6.28});
  efBolhas=efBolhas.filter(b=>b.y>-6);
  for(const b of efBolhas){b.y-=b.v;b.x+=Math.sin(b.w+t/300)*0.3;
   efCtx.beginPath();efCtx.arc(b.x,b.y,b.r,0,6.28);efCtx.fillStyle='rgba(255,224,160,.55)';efCtx.fill();}
 }else{                                             // céu estrelado + meteoros
  efCtx.fillStyle='#0a0a1e';efCtx.fillRect(0,0,efW,efH);
  for(const s of efEstrelas){const a=0.35+0.55*Math.abs(Math.sin(s.f+t/380));
   efCtx.beginPath();efCtx.arc(s.x,s.y,s.r,0,6.28);efCtx.fillStyle='rgba(200,210,255,'+a+')';efCtx.fill();}
  if(Math.random()<0.55)efMeteoros.push({x:Math.random()*efW*1.2-efW*0.1,y:-5,len:Math.random()*10+8,v:Math.random()*3+3});
  efMeteoros=efMeteoros.filter(m=>m.y<efH+10&&m.x<efW+14);
  for(const m of efMeteoros){m.x+=m.v;m.y+=m.v*1.1;
   efCtx.strokeStyle='rgba(185,205,255,.9)';efCtx.lineWidth=1.3;
   efCtx.beginPath();efCtx.moveTo(m.x,m.y);efCtx.lineTo(m.x-m.len,m.y-m.len*1.1);efCtx.stroke();}}}
function efLaco(t){efCena(t||0);efRaf=requestAnimationFrame(efLaco);}
function ligarEsforcoAnim(on){if(on){if(!efRaf){efMedir();efRaf=requestAnimationFrame(efLaco);}}
 else if(efRaf){cancelAnimationFrame(efRaf);efRaf=0;}}

// --- arrastar/clicar na pista ---
function efFrac(e){const r=efTrack.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));}
function efNivel(frac){return frac<0.33?'rapido':frac<0.67?'normal':'alto';}
if(efTrack){
 efTrack.addEventListener('pointerdown',e=>{efArr=true;try{efTrack.setPointerCapture(e.pointerId);}catch(_){}
  const f=efFrac(e);efPos(f);aplicarEsforco(efNivel(f),true);});
 efTrack.addEventListener('pointermove',e=>{if(!efArr)return;const f=efFrac(e);efPos(f);aplicarEsforco(efNivel(f),true);});
 efTrack.addEventListener('pointerup',()=>{efArr=false;pintarPopover();});
}
$('#effort').addEventListener('click',e=>{e.stopPropagation();const pop=$('#effort-pop');abrirEsforco(!!(pop&&pop.hidden));});
document.addEventListener('click',e=>{if(!e.target.closest('.effort-wrap'))abrirEsforco(false);});
window.addEventListener('resize',()=>{if(efRaf)efMedir();});
pintarEsforco();
// Esc também interrompe
addEventListener('keydown',e=>{if(e.key==='Escape'){const b=bridge();if(b&&b.stop)b.stop()}});

// avisa o Python que a página carregou
function announce(){const b=bridge();if(b&&b.ready){demo=false;b.ready();return true}return false}
if(!announce()){let n=0;const h=setInterval(()=>{if(announce()||++n>40)clearInterval(h)},150)}

// demonstração: só roda enquanto o Python não assume
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{while(true){if(!demo){await sleep(500);continue}
 setState('espera');await sleep(2600);if(!demo)continue;
 setState('ouvindo');await sleep(2400);if(!demo)continue;
 addMessage('user','Nebell, que horas são?');setState('pensando');await sleep(1700);if(!demo)continue;
 setState('falando');addMessage('nebell','São dez horas e quinze minutos, senhor.');await sleep(3000);if(!demo)continue;
 setState('internet');await sleep(2200);if(!demo)continue;
 setState('visao');await sleep(2200);if(!demo)continue;
 setState('gravando');await sleep(2200)}})();
})();
