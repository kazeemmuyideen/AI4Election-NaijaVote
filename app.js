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
  document.querySelectorAll('.desktop-nav a').forEach((a,i)=>{const label=[t.ask,t.find,t.day][i];if(label){a.textContent=label;a.lang=lang.value;}});
  const heroButton=document.querySelector('.hero-actions .button');
  if(heroButton){heroButton.childNodes[0].textContent=t.start+' ';heroButton.lang=lang.value;}
  const heroLink=document.querySelector('.hero-actions .text-link');
  if(heroLink){heroLink.childNodes[0].textContent=t.lookup+' ';heroLink.lang=lang.value;}
  const welcome=document.querySelector('.chat-content .bot-message');
  if(welcome){welcome.textContent=t.welcome;welcome.lang=lang.value;}
  const question=document.querySelector('#question');
  if(question){question.placeholder=t.placeholder;question.lang=lang.value;}
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
  node.lang=cls==='user-message'?lang.value:'en';
  node.append(document.createTextNode(text));
  if(cls==='bot-message')node.append(speakButton(text));
  chat.append(node);
  return node;
}
function addAnswer(result){
  const node=document.createElement('div');
  node.className='chat-message bot-message';
  node.lang=result.language||'en';
  node.append(document.createTextNode(result.answer));
  if(result.notice){const note=document.createElement('p');note.lang='en';note.textContent=result.notice;node.append(note);}
  for(const source of result.citations||[]){
    const link=document.createElement('a');
    link.href=source.url;
    link.target='_blank';
    link.rel='noopener noreferrer';
    link.lang='en';
    link.textContent=`Source: ${source.title} ↗`;
    node.append(link);
  }
  node.append(speakButton(result.answer));
  chat.append(node);
  return node;
}
async function answerQuestion(question){
  question=question.trim();
  if(question.length<2||question.length>1000){
    addMessage('Please enter a question between 2 and 1000 characters.','bot-message');
    return;
  }
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
let activePollingSearch=null;
const POLLING_PAGE_SIZE=20;
document.querySelector('#lookup-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const state=stateSelect.value;
  const rawArea=document.querySelector('#area').value.trim();
  if(!state){document.querySelector('#lookup-result').textContent='Choose a state to continue.';return;}
  let lga='',ward='';
  if(rawArea.includes(',')){
    [lga,ward]=rawArea.split(',',2).map(part=>part.trim());
  }else{
    const wardMatch=rawArea.match(/^(.+?)\s+ward\s+(.+)$/i);
    if(wardMatch){lga=wardMatch[1].trim();ward=wardMatch[2].trim();}
    else lga=rawArea;
  }
  activePollingSearch={state,lga,ward};
  await loadPollingPage(0);
});
async function loadPollingPage(offset){
  const {state,lga,ward}=activePollingSearch;
  const result=document.querySelector('#lookup-result');
  result.textContent='Searching verified local records…';
  try{
    const params=new URLSearchParams({state,limit:String(POLLING_PAGE_SIZE),offset:String(offset)});
    if(lga)params.set('lga',lga);
    if(ward)params.set('ward',ward);
    const response=await fetch(`/api/polling-units?${params}`);
    if(!response.ok)throw new Error('Lookup unavailable');
    const data=await response.json();
    if(data.results?.length){
      const cards=data.results.map(unit=>{
        const item=document.createElement('article');
        item.className='unit-result';
        const label=document.createElement('strong');
        label.textContent=unit.name;
        const meta=document.createElement('span');
        meta.append(document.createTextNode(`${unit.code} · `));
        const wardButton=document.createElement('button');
        wardButton.type='button';
        wardButton.className='ward-weather';
        wardButton.textContent=unit.ward;
        wardButton.setAttribute('aria-label',`Show current weather for ${unit.ward}, ${unit.lga}`);
        meta.append(wardButton,document.createTextNode(`, ${unit.lga}`));
        const verify=document.createElement('small');
        verify.textContent=`Source: ${unit.source} · checked ${unit.verified_at}`;
        const weatherResult=document.createElement('p');
        weatherResult.className='ward-weather-result';
        weatherResult.hidden=true;
        item.append(label,meta,verify,weatherResult);
        wardButton.addEventListener('click',async()=>{
          wardButton.disabled=true;
          weatherResult.hidden=false;
          weatherResult.textContent='Checking current weather…';
          try{
            const response=await fetch(`/api/polling-units/${encodeURIComponent(unit.id)}/weather`);
            const currentWeather=await response.json();
            if(!response.ok||!currentWeather.available)throw new Error('Weather unavailable');
            const current=currentWeather.current||{};
            const conditions=weatherCondition(current.weather_code);
            const parts=[];
            if(conditions)parts.push(conditions);
            if(current.temperature_2m!==undefined)parts.push(`${current.temperature_2m}°C`);
            if(current.apparent_temperature!==undefined)parts.push(`feels like ${current.apparent_temperature}°C`);
            if(current.precipitation!==undefined)parts.push(`${current.precipitation} mm precipitation`);
            weatherResult.textContent=`Current weather for ${currentWeather.location}: ${parts.join(' · ')}. ${currentWeather.location_note} Source: Open-Meteo.`;
          }catch{
            weatherResult.textContent='Current weather is temporarily unavailable. Please try again.';
          }finally{wardButton.disabled=false;}
        });
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
      });
      if(data.notice){
        const note=document.createElement('p');
        note.className='lookup-note';
        note.textContent=data.notice;
        cards.push(note);
      }
      const pager=document.createElement('nav');
      pager.className='polling-pager';
      pager.setAttribute('aria-label','Polling unit result pages');
      const summary=document.createElement('span');
      summary.textContent=`Showing ${offset+1}–${Math.min(offset+data.count,data.total_count)} of ${data.total_count} polling units`;
      pager.append(summary);
      if(offset>0){
        const previous=document.createElement('button');
        previous.type='button';previous.textContent='Previous';
        previous.addEventListener('click',()=>loadPollingPage(Math.max(0,offset-POLLING_PAGE_SIZE)));
        pager.append(previous);
      }
      if(offset+data.count<data.total_count){
        const next=document.createElement('button');
        next.type='button';next.textContent='Next';
        next.addEventListener('click',()=>loadPollingPage(offset+POLLING_PAGE_SIZE));
        pager.append(next);
      }
      cards.push(pager);
      result.replaceChildren(...cards);
    }else{
      result.textContent=data.notice||'No matching verified record found. Check your PVC or INEC’s official locator.';
    }
  }catch{
    result.textContent='Local lookup service is unavailable. Use INEC’s official polling-unit locator below.';
  }
}
function weatherCondition(code){
  const descriptions={0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Depositing rime fog',
    51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',56:'Freezing drizzle',57:'Heavy freezing drizzle',
    61:'Light rain',63:'Rain',65:'Heavy rain',66:'Freezing rain',67:'Heavy freezing rain',71:'Light snow',
    73:'Snow',75:'Heavy snow',77:'Snow grains',80:'Light rain showers',81:'Rain showers',82:'Heavy rain showers',
    85:'Snow showers',86:'Heavy snow showers',95:'Thunderstorm',96:'Thunderstorm with hail',99:'Thunderstorm with heavy hail'};
  return descriptions[code]||'';
}
function formatWeather(weather){
  if(!weather.available)return weather.message||'Weather forecast unavailable.';
  const data=weather.data;
  const current=data?.current||{};
  const daily=data?.daily||{};
  const high=daily.temperature_2m_max?.[0];
  const low=daily.temperature_2m_min?.[0];
  const rain=daily.precipitation_probability_max?.[0];
  const parts=[];
  if(current.temperature_2m!==undefined)parts.push(`${current.temperature_2m}°C now`);
  if(low!==undefined&&high!==undefined)parts.push(`${low}–${high}°C today`);
  if(rain!==undefined)parts.push(`${rain}% maximum rain chance today`);
  return `${weather.provider||'Weather'} forecast for ${weather.location||weather.state}${parts.length?`: ${parts.join(', ')}`:''}. ${weather.attribution||'Third-party forecast only; official alerts are separate.'}`;
}
document.querySelector('#check-alerts').addEventListener('click',async()=>{
  const state=(alertState&&alertState.value)||stateSelect.value;
  const output=document.querySelector('#risk-result');
  if(!state){output.textContent='Choose your state first.';return;}
  output.textContent='Checking current advisories…';
  try{
    const [riskResult,weatherResult]=await Promise.allSettled([
      fetch(`/api/risk?state=${encodeURIComponent(state)}`),
      fetch(`/api/weather/${encodeURIComponent(state)}`)
    ]);
    const riskResponse=riskResult.status==='fulfilled'?riskResult.value:null;
    const weatherResponse=weatherResult.status==='fulfilled'?weatherResult.value:null;
    const risk=riskResponse?.ok?await riskResponse.json():null;
    const weather=weatherResponse?.ok?await weatherResponse.json():null;
    const alertText=risk
      ?risk.alerts?.length
        ?risk.alerts.map(a=>`${a.hazard}: ${a.details} (${a.severity}/100, ${a.source})`).join(' · ')
        :'No verified local hazard advisories are loaded. Check official alerts before travel; no report does not mean no risk.'
      :'Local hazard advisories are unavailable right now.';
    const weatherText=weather?formatWeather(weather):'Weather forecast is unavailable right now.';
    output.textContent=`${alertText} ${weatherText}`;
    document.querySelector('#alert-status').textContent=risk?.alerts?.length
      ?'Verified advisories available'
      :weather?.available?'Open-Meteo forecast · no verified alerts'
      :risk?'No live provider data':'Advisories unavailable';
  }catch{
    output.textContent='Forecast and local advisory services are unavailable. Check official weather and emergency sources before travel.';
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
