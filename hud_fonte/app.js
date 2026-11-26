(()=>{
const $=s=>document.querySelector(s), cv=$('#hud');
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
// O nucleo e a nuvem de particulas: cada forma e um estado, e o
// mapa das ferramentas sai do proprio nebell.py.
// A animacao de abertura (big bang) vem ligada; o Python a desliga pelo
// data-bigbang do body (nebell_config.json: big_bang=false).
const bigBang=document.body.dataset.bigbang!=='0';
const nucleo=NebellFormas.criar(cv,{particulas:30000,bigBang});
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
// ---- Markdown seguro ------------------------------------------------
// A mensagem renderizada vem do MODELO. Renderizar errado seria abrir
// XSS na janela, entao NUNCA usamos innerHTML com texto do modelo: tudo
// vira no de DOM (createElement + textContent). Reconhecemos so um
// punhado de marcacoes: bloco ```, `codigo`, **negrito**, *italico* e
// listas "- ". Qualquer outra coisa sai como texto visivel, nunca
// executada.
function mdInline(alvo,texto){
 let resto=String(texto);
 const re=/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/;
 while(resto){
  const m=re.exec(resto);
  if(!m){alvo.appendChild(document.createTextNode(resto));break}
  if(m.index>0)alvo.appendChild(document.createTextNode(resto.slice(0,m.index)));
  const tok=m[0];let el;
  if(tok[0]==='`'){el=document.createElement('code');el.textContent=tok.slice(1,-1)}
  else if(tok.slice(0,2)==='**'){el=document.createElement('strong');el.textContent=tok.slice(2,-2)}
  else{el=document.createElement('em');el.textContent=tok.slice(1,-1)}
  alvo.appendChild(el);
  resto=resto.slice(m.index+tok.length);
 }
}
function mdBlocoDeCodigo(texto){
 const wrap=document.createElement('div');wrap.className='codebloco';
 const bt=document.createElement('button');bt.type='button';bt.className='copiar';bt.textContent='copiar';
 bt.addEventListener('click',()=>{try{navigator.clipboard.writeText(texto)}catch(e){}
  bt.textContent='copiado';setTimeout(()=>{bt.textContent='copiar'},1200)});
 const pre=document.createElement('pre');const code=document.createElement('code');
 code.textContent=texto;pre.appendChild(code);
 wrap.append(bt,pre);return wrap;
}
function renderMarkdown(alvo,texto){
 alvo.replaceChildren();
 const partes=String(texto).split('```');   // par=fora, impar=bloco de codigo
 for(let i=0;i<partes.length;i++){
  if(i%2===1){
   let corpo=partes[i];const nl=corpo.indexOf('\n');
   if(nl>=0 && !corpo.slice(0,nl).includes(' '))corpo=corpo.slice(nl+1); // tira "linguagem"
   alvo.appendChild(mdBlocoDeCodigo(corpo));continue;
  }
  if(!partes[i])continue;
  let lista=null;
  for(const linha of partes[i].split('\n')){
   if(/^\s*-\s+/.test(linha)){
    if(!lista){lista=document.createElement('ul');alvo.appendChild(lista)}
    const li=document.createElement('li');mdInline(li,linha.replace(/^\s*-\s+/,''));lista.appendChild(li);continue;
   }
   lista=null;
   if(linha.trim()==='')continue;
   const p=document.createElement('div');p.className='linha';mdInline(p,linha);alvo.appendChild(p);
  }
 }
}
// Cabeçalho da mensagem: papel + hora (HH:MM), em dois campos, sem o
// "·" e sem segundos — o relógio cheio poluía o log.
function horaCurta(){return new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
function metaMsg(role){const sm=document.createElement('small');
 const pa=document.createElement('span');pa.className='papel';pa.textContent=(role==='user'?'Você':'NEBELL');
 const ho=document.createElement('span');ho.className='hora';ho.textContent=horaCurta();
 sm.append(pa,ho);return sm}
function addMessage(role,text){fecharStream();const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'nebell');
 const p=document.createElement('div');if(role==='user'){p.textContent=text}else{renderMarkdown(p,text)}
 d.append(metaMsg(role),p);const log=$('#log');log.append(d);
 while(log.children.length>60)log.firstChild.remove();log.scrollTop=log.scrollHeight}

// Bolha que se preenche enquanto ele gera. Antes o texto so aparecia
// no fim, depois de ele terminar de falar: quem olhava a janela nao
// sabia se tinha algo acontecendo.
let streamP=null;
function streamMessage(text){
 const log=$('#log');
 if(!streamP){
  const d=document.createElement('div');d.className='msg nebell streaming';
  streamP=document.createElement('div');
  d.append(metaMsg('nebell'),streamP);log.append(d);
  while(log.children.length>60)log.firstChild.remove();
 }
 renderMarkdown(streamP,text);
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
 sel.textContent='';const auto=document.createElement('option');auto.value='auto';auto.textContent='AUTOMÁTICO';sel.append(auto);
 for(const d of list){const o=document.createElement('option');o.value=String(d.index);
  o.textContent=(d.is_headset?'FONE · ':'')+(d.name||('entrada '+d.index));sel.append(o)}
 if(current!=null)sel.value=String(current);atualizarTituloMic()}
// O seletor de microfone agora mora no painel SISTEMA, com rótulo
// próprio; o nome completo do aparelho fica no tooltip do próprio select.
function atualizarTituloMic(){const sel=$('#mic');if(!sel)return;
 const op=sel.options[sel.selectedIndex];sel.title=op?op.textContent:''}
// Seletor de voz: o Python manda a lista (só as vozes que funcionam
// nesta máquina) e qual está em uso. Trocar aqui muda a voz na hora.
function setVozes(list,atual){const sel=$('#vozSel');if(!sel||!Array.isArray(list))return;
 sel.textContent='';
 for(const v of list){const o=document.createElement('option');o.value=v.chave||'';o.textContent=v.rotulo||v.chave||'voz';sel.append(o)}
 if(atual!=null&&atual!=='')sel.value=String(atual);}
function setVozAtual(ch){const sel=$('#vozSel');if(sel&&ch!=null&&ch!=='')sel.value=String(ch)}
// Botão de microfone (clique-para-falar). A NEBELL NÃO escuta por conta
// própria: ela só abre o microfone por uma fala quando este botão é
// clicado, igual ao ditado do ChatGPT. O Python é quem manda o estado de
// verdade (ligou a escuta / terminou de capturar), e o visual segue o
// aria-pressed: aceso = ouvindo agora.
function setEscutando(on){const b=$('#micbtn');if(!b)return;
 b.setAttribute('aria-pressed',on?'true':'false');
 b.title=on?'Ouvindo… clique para parar':'Clique para falar';}
function submit(text){text=text.trim();if(!text)return;marcarAtividade();addMessage('user',text);
 const b=bridge();
 if(b&&b.send){demo=false;setState('pensando');b.send(text)}
 else if(api.onSubmit)api.onSubmit(text);
 else{setState('pensando');setTimeout(()=>{setState('falando');addMessage('nebell','Modo demonstração, senhor. Estou pronto para ser conectado.');setTimeout(()=>setState('espera'),2200)},1100)}}
// Historico de conversas: lista as antigas e deixa continuar numa delas.
// A lista vem do Python (pedir_conversas, que devolve uma Promise);
// clicar num item pede para continuar aquela conversa (abrir_conversa).
function limparLog(){const log=$('#log');if(log)log.replaceChildren();streamP=null}
function renderConversas(lista){
 const box=$('#hist-lista');if(!box)return;box.replaceChildren();
 if(!Array.isArray(lista)||!lista.length){
  const v=document.createElement('div');v.className='hist-vazio';v.textContent='Sem conversas anteriores.';box.appendChild(v);return}
 for(const c of lista){
  const it=document.createElement('button');it.type='button';it.className='hist-item';
  const t=document.createElement('div');t.className='hist-tit';t.textContent=c.titulo||'conversa';
  const s=document.createElement('div');s.className='hist-sub';
  s.textContent=(c.quando||'')+(c.total?(' · '+c.total+' msgs'):'');
  it.append(t,s);
  it.addEventListener('click',()=>{const b=bridge();if(b&&b.abrir_conversa)b.abrir_conversa(c.id);abrirHist(false)});
  box.appendChild(it);
 }
}
async function carregarHist(){
 const b=bridge();
 if(b&&b.pedir_conversas){try{renderConversas(await b.pedir_conversas())}catch(e){renderConversas([])}}
 else renderConversas([{id:0,titulo:'(demonstração) sem Python conectado',quando:'agora',total:0}]);
}
function abrirHist(abrir){const pop=$('#hist-pop');if(!pop)return;pop.hidden=!abrir;if(abrir)carregarHist()}
const api={
 setState:s=>{demo=false;marcarAtividade();setState(s)},
 // O Python manda o NOME DA FERRAMENTA que esta rodando; a forma
 // sai do mapa que ja existe no nebell.py.
 paraFerramenta:nome=>{demo=false;marcarAtividade();
  if(nucleo.paraFerramenta(nome)){const n=nucleo.numeros;
   $('#state').textContent=n.rotulo;$('#sub').textContent=n.diz;
   document.body.dataset.state=FAMILIA[n.estado]||'trabalhando'}},
 setEsforco:v=>nucleo.setEsforco(v),
 setEsforcoNivel:n=>aplicarEsforco(String(n),false),
 setLevel:v=>nucleo.setLevel(v),
 addMessage,streamMessage,fecharStream,trabalhando,setStats,setMics,
 setVozes,setVozAtual,setEscutando,setConversas:renderConversas,limparLog,
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

// 3.7 Easter eggs nas particulas: quando ela fica MUITO tempo parada --
// em espera, microfone mudo e nada acontecendo -- de vez em quando uma
// ondulacao discreta percorre a nuvem. Camada separada: so chama
// explodir() (API publica), nunca toca no laco base. Desligado em
// prefers-reduced-motion e enquanto o Python nao assumiu (demo).
let ultimaAtividade=Date.now();
function marcarAtividade(){ultimaAtividade=Date.now()}
function brincadeiraOciosa(){
 if(reduce||demo)return;
 const b=$('#micbtn');
 if(b&&b.getAttribute('aria-pressed')==='true')return;    // não enquanto ouve
 const n=nucleo.numeros;
 if(n.estado!=='espera'||n.viajando)return;                // só parada, em espera
 if(Date.now()-ultimaAtividade<180000)return;              // 3 min sem nada
 if(Math.random()<0.28)                                    // rara
  nucleo.explodir((Math.random()-0.5)*0.5,(Math.random()-0.5)*0.5);
}
setInterval(brincadeiraOciosa,8000);

// controles
$('#txt').addEventListener('keydown',e=>{marcarAtividade();if(e.key==='Enter'){submit(e.target.value);e.target.value=''}});
$('#mic').addEventListener('change',e=>{atualizarTituloMic();const b=bridge();if(b&&b.set_mic)b.set_mic(e.target.value)});
// Trocar a voz pelo seletor do painel SISTEMA.
$('#vozSel').addEventListener('change',e=>{const v=e.target.value;if(!v)return;const b=bridge();if(b&&b.set_voz)b.set_voz(v)});
// Microfone (clique-para-falar): um clique abre a escuta por uma fala; o
// Python captura, responde e devolve ao repouso. Clicar de novo enquanto
// ouve cancela. É o Python que confirma o estado via setEscutando; sem
// Python conectado (demo), alterna só o visual para dar retorno.
$('#micbtn').addEventListener('click',()=>{marcarAtividade();const br=bridge();
 if(br&&br.escutar){br.escutar();return}
 const b=$('#micbtn');setEscutando(b.getAttribute('aria-pressed')!=='true')});
$('#halt').addEventListener('click',()=>{const b=bridge();if(b&&b.stop)b.stop()});
// Histórico: abre/fecha o painel; fora dele, fecha.
$('#hist').addEventListener('click',e=>{e.stopPropagation();const pop=$('#hist-pop');abrirHist(!!(pop&&pop.hidden))});
document.addEventListener('click',e=>{if(!e.target.closest('.hist-wrap'))abrirHist(false)});
// Nova conversa: limpa a janela na hora e pede ao Python para comecar do zero.
$('#hist-nova').addEventListener('click',()=>{const b=bridge();if(b&&b.nova_conversa)b.nova_conversa();limparLog();abrirHist(false)});
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
 if(nivelEsforco==='rapido'){                       // azul-violeta calmo
  const g=efCtx.createLinearGradient(0,0,efW,0);g.addColorStop(0,'#1d2a66');g.addColorStop(1,'#4f6fd8');
  efCtx.fillStyle=g;efCtx.fillRect(0,0,efW,efH);
  const x=((t/1500)%1)*efW;const gg=efCtx.createLinearGradient(x-40,0,x+40,0);
  gg.addColorStop(0,'rgba(255,255,255,0)');gg.addColorStop(.5,'rgba(255,255,255,.16)');gg.addColorStop(1,'rgba(255,255,255,0)');
  efCtx.fillStyle=gg;efCtx.fillRect(0,0,efW,efH);
 }else if(nivelEsforco==='normal'){                 // violeta borbulhando (a cor da marca)
  const g=efCtx.createLinearGradient(0,0,0,efH);g.addColorStop(0,'#4a2596');g.addColorStop(1,'#8b5cf0');
  efCtx.fillStyle=g;efCtx.fillRect(0,0,efW,efH);
  if(Math.random()<0.32)efBolhas.push({x:Math.random()*efW,y:efH+4,r:Math.random()*3+1.5,v:Math.random()*0.6+0.4,w:Math.random()*6.28});
  efBolhas=efBolhas.filter(b=>b.y>-6);
  for(const b of efBolhas){b.y-=b.v;b.x+=Math.sin(b.w+t/300)*0.3;
   efCtx.beginPath();efCtx.arc(b.x,b.y,b.r,0,6.28);efCtx.fillStyle='rgba(214,186,255,.6)';efCtx.fill();}
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
