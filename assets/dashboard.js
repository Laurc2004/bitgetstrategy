'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,n=2)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n});
const signed=(v,n=2)=>(v>0?'+':'')+num(v,n);
const time=v=>v?new Date(v).toISOString().replace('T',' ').slice(0,16)+' UTC':'—';
const short=v=>v?new Date(v).toISOString().slice(5,16).replace('T',' '):'—';
const age=(at,now)=>at?Math.max(0,(new Date(now)-new Date(at))/1000):Infinity;
const cls=v=>v>0?'positive':v<0?'negative':'';
let mode='history',history=null,live=null,source='snapshot',index=0,selected='QQQ',filter='fill',timer=null,current=null,visibleEvents=[];
const reason={trend_entry:'突破确认入场',breakout_entry:'突破确认入场',signal_exit:'跌破退出通道',trailing_stop:'触发跟踪止损',account_stop:'触发账户回撤停止',planned_end_exit:'回测计划结束退出',buy_expired:'买单等待超时'};

async function loadHistory(){
  const response=await fetch('data/replay.json');
  if(!response.ok)throw Error('历史回放文件加载失败');
  history=await response.json();index=history.snapshots.length-1;
  $('timeline').max=index;$('range-start').textContent=time(history.start);$('range-end').textContent=time(history.end);
}
async function loadLive(){
  const local=['localhost','127.0.0.1','[::1]'].includes(location.hostname);
  if(local){
    try{const r=await fetch('/api/live',{cache:'no-store'});if(!r.ok)throw Error(r.status);live=await r.json();source='local';return;}
    catch(e){source='local_unavailable';}
  }
  const r=await fetch('data/live.json',{cache:'no-store'});
  if(!r.ok)throw Error('尚未发布前向模拟快照');
  live=await r.json();if(source!=='local_unavailable')source='snapshot';
}

function signalInfo(row,asof){
  const s=row.signal;
  if(mode==='live'&&age(row.mark_at,asof)>300)return ['行情待更新','最新完成分钟尚未更新，等待新数据；当前不会用陈旧行情触发新入场。'];
  if(row.pending)return ['订单等待成交',`${reason[row.pending.reason]||row.pending.reason}，后续满足时序与成交量条件的完整分钟才会模拟成交。`];
  if(!s)return ['等待完成 K 线','当前还没有本账户记录的四小时决策。历史预热数据不产生前向交易，等待下一次有效决策。'];
  if(!s.ready)return ['数据窗口不足','四小时窗口的有效分钟数、报价新鲜度或历史波动样本不足，暂不生成入场信号。'];
  if(s.leave)return [row.quantity>0?'退出信号':'保持空仓','最近一次有效决策显示价格跌破历史退出通道；持仓时进入退出流程，空仓时不做空。'];
  if(s.enter)return [row.quantity>0?'突破确认 · 持仓中':'突破确认',`最近一次有效决策确认守住原突破位，仓位缩放系数为 ${num(s.scale,2)}。是否成交仍由现金、时序和成交量决定。`];
  return [row.quantity>0?'持仓观察':'等待突破','最近一次有效决策没有产生入场或通道退出信号；持仓仍受跟踪止损与账户回撤约束。'];
}

function chart(points){
  if(!points.length){$('chart').innerHTML='<div class="empty">前向账户已建立，等待第一根新增完成分钟。</div>';return;}
  const w=760,h=235,left=58,right=18,top=14,bottom=28;
  let lo=Math.min(10000,...points.map(p=>p.equity)),hi=Math.max(10000,...points.map(p=>p.equity));
  const pad=Math.max(5,(hi-lo)*.16);lo-=pad;hi+=pad;
  const first=new Date(points[0].timestamp).getTime(),last=new Date(points.at(-1).timestamp).getTime();
  const x=t=>left+(new Date(t).getTime()-first)/Math.max(1,last-first)*(w-left-right);
  const y=v=>top+(hi-v)/(hi-lo)*(h-top-bottom);
  const line=points.map((p,i)=>(i?'L':'M')+x(p.timestamp).toFixed(2)+','+y(p.equity).toFixed(2)).join(' ');
  const end=points.at(-1);let grid='';
  for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;grid+=`<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" stroke="#273540"/><text x="${left-9}" y="${y(v)+3}" text-anchor="end">${num(v,0)}</text>`;}
  $('chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="截至 ${esc(time(end.timestamp))}，净值 ${num(end.equity)} USDT"><defs><linearGradient id="fade" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#9ee8bf" stop-opacity=".16"/><stop offset="100%" stop-color="#9ee8bf" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${line} L${x(end.timestamp)},${h-bottom} L${left},${h-bottom} Z" fill="url(#fade)"/><line x1="${left}" x2="${w-right}" y1="${y(10000)}" y2="${y(10000)}" stroke="#90a5b2" stroke-dasharray="4 5" opacity=".65"/><path d="${line}" fill="none" stroke="#9ee8bf" stroke-width="2" stroke-linejoin="round"/><circle cx="${x(end.timestamp)}" cy="${y(end.equity)}" r="4" fill="#9ee8bf"/><text x="${left}" y="${h-4}">${esc(short(points[0].timestamp))}</text><text x="${w-right}" y="${h-4}" text-anchor="end">${esc(short(end.timestamp))}</text></svg>`;
}

function render(){
  const historical=mode==='history';
  if((historical&&!history)||(!historical&&!live))return;
  const snap=historical?history.snapshots[index]:live;
  const asof=historical?snap.timestamp:new Date().toISOString();current=snap;
  let events=historical?history.events.filter(e=>new Date(e.timestamp)<=new Date(snap.timestamp)):live.events;
  visibleEvents=events;
  const pnl=snap.equity-10000;
  $('equity').textContent=num(snap.equity);$('pnl').textContent=signed(pnl);$('pnl').className=cls(pnl);
  $('return').textContent=signed(pnl/100)+'% · 已扣模拟成本';
  $('fees').textContent='累计手续费 '+num(snap.fees)+' USDT';
  $('trades').textContent=(historical?events.filter(e=>e.kind==='trade').length:live.closed_cycles)+' / '+snap.fills_count;
  $('cash').textContent='现金 '+num(snap.cash)+' USDT';
  $('asof').textContent=time(historical?snap.timestamp:live.generated_at);
  $('replay-controls').hidden=!historical;$('forward-progress').hidden=historical;
  $('context').classList.remove('error');
  let points,drawdown;
  if(historical){
    $('connection').textContent='历史数据 · 可交互回放';
    $('context').textContent='90 天开发回测 · 此区间已用于调参。时间轴只展示所选时刻之前的账户与交易；不属于新增样本外验证。';
    $('account-note').textContent='历史账户 · 初始 10,000 USDT';
    points=history.snapshots.slice(0,index+1);drawdown=snap.max_drawdown_pct;
    $('timeline').value=index;$('step-count').textContent=(index+1)+' / '+history.snapshots.length;
  }else{
    const lag=age(live.generated_at,asof),running=['running','data_degraded'].includes(live.status);
    const connected=source==='local'&&lag<180&&running;
    $('connection').textContent=connected?'本机模拟账户 · 每 10 秒读取':source==='local'?'本机账户 · 状态待检查':'公开状态快照 · 非实时连接';
    let note=source==='local'?'前向模拟 · 从冻结时刻开始独立记账，仅处理此后观测到的行情。':'公开页面展示最近发布的前向账户快照；本机演示台连接持续运行的模拟账户。';
    if(lag>=180)note+=' 快照已超过 3 分钟未更新，请查看时间戳。';
    if(!running)note+=' 账户状态：'+({warming_up:'指标预热中',snapshot_only:'单次快照已完成',stopped:'已停止',observation_complete:'观察期结束',runner_error:'运行错误',starting:'正在启动'}[live.status]||live.status)+'。';
    if(live.errors.length)note+=' 数据异常：'+live.errors.join('；');
    if(live.halted)note+=' 账户回撤停止已触发，禁止新增入场。';
    $('context').textContent=note;$('context').classList.toggle('error',live.errors.length>0||live.halted||lag>=180);
    $('account-note').textContent='前向账户 · 独立初始 10,000 USDT';
    points=live.curve;drawdown=live.max_drawdown_pct;
    const p=live.protocol,total=new Date(p.ends_at)-new Date(p.started_at);
    const observed=Math.max(0,new Date(live.generated_at)-new Date(p.started_at));
    $('forward-progress').innerHTML=`<span>冻结：${esc(time(p.started_at))}</span><div class="progress-track"><i style="width:${Math.min(100,observed/total*100)}%"></i></div><span>计划观察至 ${esc(time(p.ends_at))} · 当前 ${num(observed/3600000,1)} 小时 · 参数 ${esc(p.config_sha256.slice(0,12))}</span>`;
  }
  $('drawdown').textContent=num(drawdown)+'%';chart(points);
  $('markets').innerHTML=snap.symbols.map(row=>{
    const q=row.quote,price=q?q.price:row.mark;
    const [label]=signalInfo(row,asof);
    const freshness=q?age(q.exchange_at,asof):age(row.mark_at,asof);
    const change=q?(signed(q.change_pct)+'%'):'历史分钟收盘';
    return `<button class="market ${row.symbol===selected?'selected':''}" data-symbol="${esc(row.symbol)}" aria-pressed="${row.symbol===selected}"><div class="market-top"><b>r${esc(row.symbol)}</b><span class="${q?cls(q.change_pct):'muted'}">${esc(change)}</span></div><span class="price">${num(price)}</span><small>${q?'报价':'完成分钟'} ${esc(short(q?q.exchange_at:row.mark_at))} UTC ${freshness>300?'· 待更新':''}</small><div class="state"><span>${esc(label)}</span><span>${row.quantity>0?'● 持仓':'○ 空仓'}</span></div></button>`;
  }).join('');
  for(const b of $('markets').querySelectorAll('button'))b.onclick=()=>{selected=b.dataset.symbol;render();};
  const row=snap.symbols.find(r=>r.symbol===selected)||snap.symbols[0],info=signalInfo(row,asof);
  $('selected-name').textContent='r'+row.symbol;$('signal-badge').textContent=info[0];$('signal-text').textContent=info[1];
  $('decision-detail').textContent='最近决策：'+time(row.signal?.timestamp)+' · 当前数量 '+num(row.quantity)+' · '+(historical?'历史下一分钟执行模型':'实际接收后首个完整分钟执行模型');
  $('positions').innerHTML=snap.symbols.map(r=>`<tr><td>r${esc(r.symbol)}</td><td>${num(r.quantity)}</td><td>${r.quantity>0?num(r.average):'—'}</td><td class="${cls(r.quantity*((r.mark||0)-r.average))}">${r.quantity>0?signed(r.quantity*((r.mark||0)-r.average)):'—'}</td></tr>`).join('');
  const stale=snap.symbols.some(r=>r.quantity>0&&age(r.mark_at,asof)>300);
  $('valuation-note').textContent=stale?'持仓估值包含超过 5 分钟的旧价格；缺口期间的风险可能被低估。':'估值采用已记录的完成分钟价格；行情卡片的最新报价不直接计入账户净值。';
  renderEvents(events);
}

function renderEvents(events){
  const shown=events.filter(e=>filter==='all'||e.kind===filter).slice().sort((a,b)=>new Date(b.timestamp)-new Date(a.timestamp)).slice(0,60);
  $('events').innerHTML=shown.length?shown.map(e=>{
    let label=reason[e.reason]||e.reason||({signal:'四小时信号',cancel:'取消订单'}[e.kind]||e.kind),amount='',sub='';
    if(e.kind==='fill'){amount=(e.quantity>0?'买入 ':'卖出 ')+num(Math.abs(e.quantity));sub='价格 '+num(e.price)+' · 费 '+num(e.fee,3);}
    if(e.kind==='trade'){amount=signed(e.net_pnl)+' U';sub='完整交易 · 已扣费';}
    if(e.kind==='order'){amount='目标 '+num(e.target);sub='等待后续分钟执行';}
    if(e.kind==='signal'){amount=e.ready?(e.enter?'入场确认':e.leave?'通道退出':'观察'):'样本不足';sub='仓位缩放 '+num(e.scale,2);}
    return `<div class="event"><time>${esc(short(e.timestamp))}<small>UTC</small></time><div>r${esc(e.symbol)} · ${esc(label)}<small>${esc(sub)}</small></div><div class="event-num ${e.kind==='trade'?cls(e.net_pnl):''}">${esc(amount)}</div></div>`;
  }).join(''):'<div class="empty">此时尚无'+({fill:'模拟成交',order:'订单',trade:'完整交易',all:'事件'}[filter])+'。等待数据和策略条件满足。</div>';
}

function stop(){if(timer)clearInterval(timer);timer=null;$('play').textContent='▶ 播放回测';}
async function setMode(value){
  stop();mode=value;
  $('history-tab').classList.toggle('active',mode==='history');$('history-tab').setAttribute('aria-selected',mode==='history');
  $('live-tab').classList.toggle('active',mode==='live');$('live-tab').setAttribute('aria-selected',mode==='live');
  if(mode==='live'){
    for(const id of ['equity','pnl','return','drawdown','trades','fees','cash','asof'])$(id).textContent='—';
    $('markets').innerHTML='';$('positions').innerHTML='';$('events').innerHTML='';
    $('chart').innerHTML='<div class="empty">正在连接前向账户…</div>';
    $('context').textContent='正在读取前向账户，历史账户指标已隐藏。';
    $('connection').textContent='正在连接…';$('replay-controls').hidden=true;
    $('forward-progress').hidden=true;$('signal-badge').textContent='等待连接';
    $('signal-text').textContent='';$('decision-detail').textContent='';
  }
  try{if(mode==='live')await loadLive();render();}catch(e){$('context').textContent=e.message;$('context').classList.add('error');$('connection').textContent='数据未连接';}
}
$('history-tab').onclick=()=>setMode('history');$('live-tab').onclick=()=>setMode('live');
$('refresh').onclick=async()=>{try{if(mode==='live')await loadLive();render();}catch(e){$('context').textContent=e.message;}};
$('timeline').oninput=e=>{stop();index=Number(e.target.value);render();};
$('play').onclick=()=>{if(!history)return;if(timer){stop();return;}if(index>=history.snapshots.length-1)index=0;$('play').textContent='Ⅱ 暂停';timer=setInterval(()=>{render();if(index>=history.snapshots.length-1)stop();else index++;},180);};
$('next-fill').onclick=()=>{if(!history)return;stop();let next=history.events.find(e=>e.kind==='fill'&&new Date(e.timestamp)>new Date(history.snapshots[index].timestamp));if(!next)next=history.events.find(e=>e.kind==='fill');if(next){index=history.snapshots.findIndex(s=>new Date(s.timestamp)>=new Date(next.timestamp));render();}};
for(const b of document.querySelectorAll('[data-filter]'))b.onclick=()=>{filter=b.dataset.filter;for(const el of document.querySelectorAll('[data-filter]'))el.classList.toggle('active',el===b);render();};
$('export').onclick=()=>{
  const keys=['kind','timestamp','symbol','quantity','price','fee','net_pnl','reason','observed_at'];
  const cell=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
  const rows=[keys.join(','),...visibleEvents.filter(e=>filter==='all'||e.kind===filter).map(e=>keys.map(k=>cell(e[k])).join(','))];
  const url=URL.createObjectURL(new Blob(['\ufeff'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='rtoken-'+mode+'-'+filter+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
(async()=>{try{await loadHistory();render();if(location.hash==='#live')await setMode('live');}catch(e){$('context').textContent=e.message;$('context').classList.add('error');$('connection').textContent='加载失败';}})();
setInterval(async()=>{if(mode==='live'){try{await loadLive();render();}catch(e){$('connection').textContent='读取失败 · 保留旧数据';$('context').textContent='无法更新账户状态，请检查本机服务。';$('context').classList.add('error');}}},10000);
