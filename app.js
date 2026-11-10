const translations = {
  en: {ask:'Ask a question',find:'Find your PU',day:'Election day',start:'Ask a question',lookup:'Find my polling unit',welcome:'Hello! I can help you understand voting and your rights. What’s on your mind?',placeholder:'Type your question here…'},
  pcm: {ask:'Ask question',find:'Find your PU',day:'Election day',start:'Ask question',lookup:'Find my polling unit',welcome:'How far! I fit help you understand voting and your rights. Wetin dey your mind?',placeholder:'Type your question here…'},
  ha: {ask:'Yi tambaya',find:'Nemo PU ɗinka',day:'Ranar zaɓe',start:'Yi tambaya',lookup:'Nemo wurin zaɓe na',welcome:'Sannu! Zan iya taimaka maka ka fahimci zaɓe da haƙƙoƙinka. Me kake son sani?',placeholder:'Rubuta tambayarka a nan…'},
  ig: {ask:'Jụọ ajụjụ',find:'Chọta ebe ị ga-atụ vootu',day:'Ụbọchị ntuli aka',start:'Jụọ ajụjụ',lookup:'Chọta ebe m ga-atụ vootu',welcome:'Nnọọ! Enwere m ike inyere gị aka ịghọta ntuli aka na ikike gị. Kedu ihe ị chọrọ ịma?',placeholder:'Dee ajụjụ gị ebe a…'},
  yo: {ask:'Béèrè ìbéèrè',find:'Wa ibùdó ìdìbò rẹ',day:'Ọjọ́ ìdìbò',start:'Béèrè ìbéèrè',lookup:'Wa ibùdó ìdìbò mi',welcome:'Ẹ káàbọ̀! Mo lè ràn yín lọ́wọ́ láti lóye ìdìbò àti ẹ̀tọ́ yín. Kí ni ẹ fẹ́ mọ̀?',placeholder:'Tẹ ìbéèrè rẹ síbí…'}
};
const INEC_EDUCATION='https://www.inecnigeria.org/voters/education';
const stateSelect=document.querySelector('#state');
const nigeriaStates=['Abia','Adamawa','Akwa Ibom','Anambra','Bauchi','Bayelsa','Benue','Borno','Cross River','Delta','Ebonyi','Edo','Ekiti','Enugu','Federal Capital Territory','Gombe','Imo','Jigawa','Kaduna','Kano','Katsina','Kebbi','Kogi','Kwara','Lagos','Nasarawa','Niger','Ogun','Ondo','Osun','Oyo','Plateau','Rivers','Sokoto','Taraba','Yobe','Zamfara'];
const stateOptions='<option value="">Select a state</option>'+nigeriaStates.map(s=>`<option>${s}</option>`).join('');
stateSelect.innerHTML=stateOptions;
const alertState=document.querySelector('#alert-state');
if(alertState)alertState.innerHTML=stateOptions;
const lang = document.querySelector('#language');
const voiceLang={en:'en-NG',pcm:'en-NG',ha:'ha-NG',ig:'ig-NG',yo:'yo-NG'};
lang.addEventListener('change', () => {
  const t = translations[lang.value] || translations.en;
  document.querySelectorAll('.desktop-nav a').forEach((a,i)=>{const label=[t.ask,t.find,t.day][i];if(label)a.textContent=label;});
  const heroButton=document.querySelector('.hero-actions .button');
  if(heroButton)heroButton.childNodes[0].textContent=t.start+' ';
  const heroLink=document.querySelector('.hero-actions .text-link');
  if(heroLink)heroLink.childNodes[0].textContent=t.lookup+' ';
  const welcome=document.querySelector('.chat-content .bot-message');
  if(welcome)welcome.textContent=t.welcome;
  const question=document.querySelector('#question');
  if(question)question.placeholder=t.placeholder;
  document.documentElement.lang=lang.value;
});
const chat = document.querySelector('#chat-content');
function speakButton(text){
  const speak=document.createElement('button');
  speak.type='button';
  speak.className='speak-button';
  speak.textContent='Listen';
  speak.setAttribute('aria-label','Read this answer aloud');
  speak.addEventListener('click',()=>{
    if(!window.speechSynthesis)return;
    const utterance=new SpeechSynthesisUtterance(text);
    utterance.lang=voiceLang[lang.value]||'en-NG';
    window.speechSynthesis.speak(utterance);
  });
  return speak;
}
function addMessage(text, cls){
  const node=document.createElement('div');
  node.className=`chat-message ${cls}`;
  node.append(document.createTextNode(text));
  if(cls==='bot-message')node.append(speakButton(text));
  chat.append(node);
  return node;
}
function addAnswer(result){
  const node=document.createElement('div');
  node.className='chat-message bot-message';
  node.append(document.createTextNode(result.answer));
  if(result.notice){const note=document.createElement('p');note.textContent=result.notice;node.append(note);}
  for(const source of result.citations||[]){
    const link=document.createElement('a');
    link.href=source.url;
    link.target='_blank';
    link.rel='noopener noreferrer';
    link.textContent=`Source: ${source.title} ↗`;
    node.append(link);
  }
  node.append(speakButton(result.answer));
  chat.append(node);
  return node;
}
async function answerQuestion(question){
  addMessage(question,'user-message');
  try{
    const response=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,language:lang.value})});
    if(!response.ok)throw new Error('API unavailable');
    addAnswer(await response.json());
  }catch{
    // Never invent civic guidance: show a sourced fallback instead.
    addAnswer({answer:'The answer service is temporarily unavailable. Please check INEC’s official voter education information or contact your local INEC office.',citations:[{title:'INEC voter education',url:INEC_EDUCATION}]});
  }
}
document.querySelector('#chat-form').addEventListener('submit',e=>{e.preventDefault();const input=document.querySelector('#question');const q=input.value.trim();if(!q)return;answerQuestion(q);input.value='';});
document.querySelectorAll('.suggestion').forEach(button=>button.addEventListener('click',()=>answerQuestion(button.dataset.question)));
document.querySelector('#lookup-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const state=stateSelect.value;
  const rawArea=document.querySelector('#area').value.trim();
  const result=document.querySelector('#lookup-result');
  if(!state){result.textContent='Choose a state to continue.';return;}
  const [lga='',ward='']=rawArea.split(',').map(part=>part.trim());
  result.textContent='Searching verified local records…';
  try{
    const params=new URLSearchParams({state});
    if(lga)params.set('lga',lga);
    if(ward)params.set('ward',ward);
    const response=await fetch(`/api/polling-units?${params}`);
    if(!response.ok)throw new Error('Lookup unavailable');
    const data=await response.json();
    if(data.results?.length){
      result.replaceChildren(...data.results.map(unit=>{
        const item=document.createElement('article');
        item.className='unit-result';
        const label=document.createElement('strong');
        label.textContent=unit.name;
        const meta=document.createElement('span');
        meta.textContent=`${unit.code} · ${unit.ward}, ${unit.lga}`;
        const verify=document.createElement('small');
        verify.textContent=`Source: ${unit.source} · checked ${unit.verified_at}`;
        item.append(label,meta,verify);
        if(unit.latitude!==null&&unit.longitude!==null){
          const map=document.createElement('a');
          map.href=`https://www.openstreetmap.org/?mlat=${unit.latitude}&mlon=${unit.longitude}#map=16/${unit.latitude}/${unit.longitude}`;
          map.target='_blank';
          map.rel='noopener noreferrer';
          map.className='unit-map';
          map.textContent='View map ↗';
          const riskButton=document.createElement('button');
          riskButton.type='button';
          riskButton.className='unit-risk';
          riskButton.textContent='Check nearby alerts';
          riskButton.addEventListener('click',async()=>{
            riskButton.disabled=true;
            riskButton.textContent='Checking…';
            try{
              const r=await fetch(`/api/polling-units/${encodeURIComponent(unit.id)}/risk`);
              if(!r.ok)throw new Error('Risk unavailable');
              const risk=await r.json();
              riskButton.textContent=risk.risk_level==='unknown'?'Risk unknown':`${risk.risk_level} risk${risk.risk_score===null?'':` · ${risk.risk_score}/100`}`;
              riskButton.title=risk.note||'';
            }catch{riskButton.textContent='Alerts unavailable';}
          });
          item.append(map,riskButton);
        }
        return item;
      }));
    }else{
      result.textContent=data.notice||'No matching verified record found. Check your PVC or INEC’s official locator.';
    }
  }catch{
    result.textContent='Local lookup service is unavailable. Use INEC’s official polling-unit locator below.';
  }
});
function formatWeather(weather){
  if(!weather.available)return weather.message||'NiMet forecast unavailable.';
  const data=weather.data;
  if(data&&typeof data==='object'){
    const parts=[];
    for(const key of ['state','condition','description','temperature','temp','humidity','rainfall']){
      if(data[key]!==undefined&&data[key]!==null)parts.push(`${key}: ${data[key]}`);
    }
    if(parts.length)return `NiMet forecast — ${parts.join(', ')}.`;
  }
  return 'NiMet forecast data is available.';
}
document.querySelector('#check-alerts').addEventListener('click',async()=>{
  const state=(alertState&&alertState.value)||stateSelect.value;
  const output=document.querySelector('#risk-result');
  if(!state){output.textContent='Choose your state first.';return;}
  output.textContent='Checking current advisories…';
  try{
    const [riskRes,weatherRes]=await Promise.all([fetch(`/api/risk?state=${encodeURIComponent(state)}`),fetch(`/api/weather/${encodeURIComponent(state)}`)]);
    if(!riskRes.ok||!weatherRes.ok)throw new Error('Advisory service unavailable');
    const risk=await riskRes.json(),weather=await weatherRes.json();
    const alertText=risk.alerts?.length
      ?risk.alerts.map(a=>`${a.hazard}: ${a.details} (${a.severity}/100, ${a.source})`).join(' · ')
      :'No current verified local hazard report is loaded. This does not mean the area is hazard-free.';
    output.textContent=`${alertText} ${formatWeather(weather)}`;
    document.querySelector('#alert-status').textContent=risk.alerts?.length?'Verified advisories available':weather.available?'Forecast available':'No live provider data';
  }catch{
    output.textContent='Alert services are unavailable. Check NiMet and NIHSA directly before travel.';
  }
});
const voiceButton=document.querySelector('#voice-button');
voiceButton.addEventListener('click',()=>{
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){voiceButton.title='Voice input is not available in this browser';return;}
  const recognition=new Recognition();
  recognition.lang=voiceLang[lang.value]||'en-NG';
  recognition.onresult=event=>{document.querySelector('#question').value=event.results[0][0].transcript;document.querySelector('#chat-form').requestSubmit();};
  recognition.start();
});
const menuToggle=document.querySelector('#menu-toggle');
const desktopNav=document.querySelector('.desktop-nav');
function closeMenu(){desktopNav.classList.remove('mobile-nav');menuToggle.setAttribute('aria-expanded','false');menuToggle.setAttribute('aria-label','Open menu');}
menuToggle.addEventListener('click',()=>{
  const opened=menuToggle.getAttribute('aria-expanded')==='true';
  menuToggle.setAttribute('aria-expanded',String(!opened));
  menuToggle.setAttribute('aria-label',opened?'Open menu':'Close menu');
  desktopNav.classList.toggle('mobile-nav',!opened);
});
desktopNav.querySelectorAll('a').forEach(a=>a.addEventListener('click',closeMenu));
if('serviceWorker' in navigator && location.protocol.startsWith('http'))navigator.serviceWorker.register('/sw.js').catch(()=>{});
