const translations = {
  en: {ask:'Ask a question',find:'Find your PU',day:'Election day',start:'Ask a question',lookup:'Find my polling unit',welcome:'Hello! I can help you understand voting and your rights. What’s on your mind?',placeholder:'Type your question here…'},
  pcm: {ask:'Ask question',find:'Find your PU',day:'Election day',start:'Ask question',lookup:'Find my polling unit',welcome:'How far! I fit help you understand voting and your rights. Wetin dey your mind?',placeholder:'Type your question here…'},
  ha: {ask:'Yi tambaya',find:'Nemo PU ɗinka',day:'Ranar zaɓe',start:'Yi tambaya',lookup:'Nemo wurin zaɓe na',welcome:'Sannu! Zan iya taimaka maka ka fahimci zaɓe da haƙƙoƙinka. Me kake son sani?',placeholder:'Rubuta tambayarka a nan…'},
  ig: {ask:'Jụọ ajụjụ',find:'Chọta ebe ị ga-atụ vootu',day:'Ụbọchị ntuli aka',start:'Jụọ ajụjụ',lookup:'Chọta ebe m ga-atụ vootu',welcome:'Nnọọ! Enwere m ike inyere gị aka ịghọta ntuli aka na ikike gị. Kedu ihe ị chọrọ ịma?',placeholder:'Dee ajụjụ gị ebe a…'},
  yo: {ask:'Béèrè ìbéèrè',find:'Wa ibùdó ìdìbò rẹ',day:'Ọjọ́ ìdìbò',start:'Béèrè ìbéèrè',lookup:'Wa ibùdó ìdìbò mi',welcome:'Ẹ káàbọ̀! Mo lè ràn yín lọ́wọ́ láti lóye ìdìbò àti ẹ̀tọ́ yín. Kí ni ẹ fẹ́ mọ̀?',placeholder:'Tẹ ìbéèrè rẹ síbí…'}
};
const INEC_EDUCATION='https://www.inecnigeria.org/voters/education';
const API_TIMEOUT_MS=15000;
const LANG_CODES=new Set(['en','pcm','ha','ig','yo']);
const LANG_ATTR={en:'en',pcm:'en',ha:'ha',ig:'ig',yo:'yo'};
function safeLang(code){return LANG_CODES.has(code)?code:'en';}
function langAttr(code){return LANG_ATTR[safeLang(code)]||'en';}
function safeHttpsUrl(value,base=location.origin){
  try{
    const url=new URL(value,base);
    if(url.protocol!=='https:'||url.username||url.password)return null;
    return url.href;
  }catch{return null;}
}
// Bound every API wait so a stalled connection shows the sourced fallback
// instead of leaving the interface spinning indefinitely on slow mobile data.
function apiFetch(url,options={}){
  const signal=typeof AbortSignal!=='undefined'&&typeof AbortSignal.timeout==='function'?AbortSignal.timeout(API_TIMEOUT_MS):undefined;
  return fetch(url,{...options,...(signal?{signal}:{})});
}
const stateSelect=document.querySelector('#state');
const nigeriaStates=['Abia','Adamawa','Akwa Ibom','Anambra','Bauchi','Bayelsa','Benue','Borno','Cross River','Delta','Ebonyi','Edo','Ekiti','Enugu','Federal Capital Territory','Gombe','Imo','Jigawa','Kaduna','Kano','Katsina','Kebbi','Kogi','Kwara','Lagos','Nasarawa','Niger','Ogun','Ondo','Osun','Oyo','Plateau','Rivers','Sokoto','Taraba','Yobe','Zamfara'];
function fillStateSelect(select,placeholder){
  if(!select)return;
  select.replaceChildren(new Option(placeholder,''));
  for(const state of nigeriaStates)select.append(new Option(state,state));
}
fillStateSelect(stateSelect,'Select a state');
const alertState=document.querySelector('#alert-state');
fillStateSelect(alertState,'Select a state');
const lang = document.querySelector('#language');
const voiceLang={en:'en-NG',pcm:'en-NG',ha:'ha-NG',ig:'ig-NG',yo:'yo-NG'};
function currentLang(){return safeLang(lang?.value);}
lang?.addEventListener('change', () => {
  const code=currentLang();
  const t = translations[code] || translations.en;
  const uiLang=langAttr(code);
  document.querySelectorAll('.desktop-nav a').forEach((a,i)=>{const label=[t.ask,t.find,t.day][i];if(label){a.textContent=label;a.lang=uiLang;}});
  const heroButton=document.querySelector('.hero-actions .button');
  if(heroButton&&heroButton.firstChild){heroButton.firstChild.textContent=t.start+' ';heroButton.lang=uiLang;}
  const heroLink=document.querySelector('.hero-actions .text-link');
  if(heroLink&&heroLink.firstChild){heroLink.firstChild.textContent=t.lookup+' ';heroLink.lang=uiLang;}
  const welcome=document.querySelector('.chat-content .bot-message');
  if(welcome){welcome.textContent=t.welcome;welcome.lang=uiLang;}
  const question=document.querySelector('#question');
  if(question){question.placeholder=t.placeholder;question.lang=uiLang;}
});
const chat = document.querySelector('#chat-content');
function stopSpeech(){if(window.speechSynthesis)window.speechSynthesis.cancel();}
function speakButton(text,spokenLang){
  const speak=document.createElement('button');
  speak.type='button';
  speak.className='speak-button';
  speak.textContent='Listen';
  speak.setAttribute('aria-label','Read this answer aloud');
  speak.addEventListener('click',()=>{
    if(!window.speechSynthesis||typeof SpeechSynthesisUtterance==='undefined')return;
    stopSpeech();
    const utterance=new SpeechSynthesisUtterance(text);
    utterance.lang=voiceLang[safeLang(spokenLang)]||'en-NG';
    window.speechSynthesis.speak(utterance);
  });
  return speak;
}
function addMessage(text, cls){
  const node=document.createElement('div');
  node.className=`chat-message ${cls}`;
  node.lang=cls==='user-message'?langAttr(currentLang()):'en';
  node.append(document.createTextNode(String(text)));
  if(cls==='bot-message')node.append(speakButton(text,'en'));
  chat.append(node);
  return node;
}
function addAnswer(result){
  const node=document.createElement('div');
  node.className='chat-message bot-message';
  const answerLang=safeLang(result?.language);
  const answerText=typeof result?.answer==='string'?result.answer:'';
  node.lang=langAttr(answerLang);
  node.append(document.createTextNode(answerText));
  if(typeof result?.notice==='string'&&result.notice){
    const note=document.createElement('p');
    note.lang='en';
    note.textContent=result.notice;
    node.append(note);
  }
  for(const source of Array.isArray(result?.citations)?result.citations:[]){
    const href=safeHttpsUrl(source?.url);
    if(!href)continue;
    const link=document.createElement('a');
    link.href=href;
    link.target='_blank';
    link.rel='noopener noreferrer';
    link.lang='en';
    link.textContent=`Source: ${typeof source?.title==='string'&&source.title?source.title:'Official source'} ↗`;
    node.append(link);
  }
  node.append(speakButton(answerText,answerLang));
  chat.append(node);
  return node;
}
async function answerQuestion(question){
  question=String(question||'').trim();
  if(question.length<2||question.length>1000){
    addMessage('Please enter a question between 2 and 1000 characters.','bot-message');
    return;
  }
  addMessage(question,'user-message');
  try{
    const response=await apiFetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,language:currentLang()})});
    if(!response.ok)throw new Error('API unavailable');
    addAnswer(await response.json());
  }catch{
    // Never invent civic guidance: show a sourced fallback instead.
    addAnswer({language:'en',answer:'The answer service is temporarily unavailable. Please check INEC’s official voter education information or contact your local INEC office.',citations:[{title:'INEC voter education',url:INEC_EDUCATION}]});
  }
}
document.querySelector('#chat-form')?.addEventListener('submit',e=>{e.preventDefault();const input=document.querySelector('#question');const q=input?.value.trim()||'';if(!q)return;answerQuestion(q);input.value='';});
document.querySelectorAll('.suggestion').forEach(button=>button.addEventListener('click',()=>answerQuestion(button.dataset.question||'')));
let activePollingSearch=null;
const POLLING_PAGE_SIZE=100;
let pollingOffset=0;
const lgaSelect=document.querySelector('#lga');
const wardSelect=document.querySelector('#ward');
const lookupSubmit=document.querySelector('#lookup-submit');
function resetSelect(select,placeholder){
  if(!select)return;
  select.replaceChildren(new Option(placeholder,''));
  select.disabled=true;
}
async function loadPollingAreas(state,lga=''){
  const params=new URLSearchParams({state});
  if(lga)params.set('lga',lga);
  const response=await apiFetch(`/api/polling-unit-areas?${params}`);
  if(!response.ok)throw new Error('Area list unavailable');
  const data=await response.json();
  return Array.isArray(data?.areas)?data.areas.filter(a=>typeof a==='string'&&a):[];
}
stateSelect?.addEventListener('change',async()=>{
  resetSelect(lgaSelect,'Loading LGAs…');
  resetSelect(wardSelect,'Select a ward');
  if(lookupSubmit)lookupSubmit.disabled=true;
  document.querySelector('#lookup-result')?.replaceChildren();
  if(!stateSelect.value){resetSelect(lgaSelect,'Select an LGA');return;}
  try{
    const lgas=await loadPollingAreas(stateSelect.value);
    lgaSelect.replaceChildren(new Option(lgas.length?'Select an LGA':'No local LGAs loaded',''),...lgas.map(area=>new Option(area,area)));
    lgaSelect.disabled=!lgas.length;
  }catch{resetSelect(lgaSelect,'Could not load LGAs');}
});
lgaSelect?.addEventListener('change',async()=>{
  resetSelect(wardSelect,'Loading wards…');
  if(lookupSubmit)lookupSubmit.disabled=true;
  document.querySelector('#lookup-result')?.replaceChildren();
  if(!lgaSelect.value){resetSelect(wardSelect,'Select a ward');return;}
  try{
    const wards=await loadPollingAreas(stateSelect.value,lgaSelect.value);
    wardSelect.replaceChildren(new Option(wards.length?'Select a ward':'No local wards loaded',''),...wards.map(area=>new Option(area,area)));
    wardSelect.disabled=!wards.length;
  }catch{resetSelect(wardSelect,'Could not load wards');}
});
wardSelect?.addEventListener('change',()=>{if(lookupSubmit)lookupSubmit.disabled=!wardSelect.value;});
document.querySelector('#lookup-form')?.addEventListener('submit',async e=>{
  e.preventDefault();
  const state=stateSelect?.value||'';
  const lga=lgaSelect?.value||'',ward=wardSelect?.value||'';
  if(!state||!lga||!ward)return;
  activePollingSearch={state,lga,ward};
  pollingOffset=0;
  await loadPollingUnits();
});
function asText(value,fallback=''){return typeof value==='string'&&value.trim()?value:fallback;}
function asFiniteNumber(value){const n=Number(value);return Number.isFinite(n)?n:null;}
async function loadPollingUnits(){
  if(!activePollingSearch)return;
  const {state,lga,ward}=activePollingSearch;
  const result=document.querySelector('#lookup-result');
  if(!result)return;
  if(pollingOffset===0)result.textContent='Searching verified local records…';
  else{
    const more=result.querySelector('.load-more-units');
    if(more){more.disabled=true;more.textContent='Loading…';}
  }
  try{
    const params=new URLSearchParams({state,limit:String(POLLING_PAGE_SIZE),offset:String(pollingOffset)});
    if(lga)params.set('lga',lga);
    if(ward)params.set('ward',ward);
    const response=await apiFetch(`/api/polling-units?${params}`);
    if(!response.ok)throw new Error('Lookup unavailable');
    const data=await response.json();
    const rows=Array.isArray(data?.results)?data.results:[];
    const count=Number.isInteger(data?.count)?data.count:rows.length;
    const totalCount=Number.isInteger(data?.total_count)?data.total_count:count;
    if(rows.length){
      const cards=rows.map(raw=>{
        const unit=raw&&typeof raw==='object'?raw:{};
        const name=asText(unit.name,'Unnamed polling unit');
        const code=asText(unit.code,'Code unavailable');
        const wardName=asText(unit.ward,ward||'Ward unavailable');
        const lgaName=asText(unit.lga,lga||'LGA unavailable');
        const stateName=asText(unit.state,state||'State unavailable');
        const source=asText(unit.source,'Unspecified source');
        const verifiedAt=asText(unit.verified_at,'unverified date');
        const unitId=asText(unit.id,'');
        const lat=asFiniteNumber(unit.latitude);
        const lon=asFiniteNumber(unit.longitude);
        const hasCoords=lat!==null&&lon!==null&&lat>=-90&&lat<=90&&lon>=-180&&lon<=180;

        const item=document.createElement('article');
        item.className='unit-result';
        const label=document.createElement('strong');
        label.textContent=name;
        const meta=document.createElement('span');
        meta.append(document.createTextNode(`${code} · `));
        const wardButton=document.createElement('button');
        wardButton.type='button';
        wardButton.className='ward-weather';
        wardButton.textContent=wardName;
        wardButton.setAttribute('aria-label',`Show current weather for ${wardName}, ${lgaName}`);
        meta.append(wardButton,document.createTextNode(`, ${lgaName}`));
        const verify=document.createElement('small');
        verify.textContent=`Source: ${source} · checked ${verifiedAt}`;
        const weatherResult=document.createElement('p');
        weatherResult.className='ward-weather-result';
        weatherResult.hidden=true;
        item.append(label,meta,verify,weatherResult);

        wardButton.addEventListener('click',async()=>{
          if(!unitId){weatherResult.hidden=false;weatherResult.textContent='Current weather is unavailable for this record.';return;}
          wardButton.disabled=true;
          weatherResult.hidden=false;
          weatherResult.textContent='Checking current weather…';
          try{
            const response=await apiFetch(`/api/polling-units/${encodeURIComponent(unitId)}/weather`);
            const currentWeather=await response.json().catch(()=>null);
            if(!response.ok||!currentWeather?.available)throw new Error('Weather unavailable');
            const current=currentWeather.current&&typeof currentWeather.current==='object'?currentWeather.current:{};
            const conditions=weatherCondition(current.weather_code);
            const parts=[];
            if(conditions)parts.push(conditions);
            const temp=asFiniteNumber(current.temperature_2m);
            const feels=asFiniteNumber(current.apparent_temperature);
            const precip=asFiniteNumber(current.precipitation);
            if(temp!==null)parts.push(`${temp}°C`);
            if(feels!==null)parts.push(`feels like ${feels}°C`);
            if(precip!==null)parts.push(`${precip} mm precipitation`);
            const where=asText(currentWeather.location,'this location');
            const note=asText(currentWeather.location_note,'');
            weatherResult.textContent=`Current weather for ${where}: ${parts.join(' · ')||'details unavailable'}.${note?` ${note}`:''} Source: Open-Meteo.`;
          }catch{
            weatherResult.textContent='Current weather is temporarily unavailable. Please try again.';
          }finally{wardButton.disabled=false;}
        });

        const destination=hasCoords?`${lat},${lon}`:`${name}, ${wardName}, ${lgaName}, ${stateName}, Nigeria`;
        const directions=document.createElement('a');
        directions.className='unit-directions';
        directions.href=`https://www.google.com/maps/dir/?api=1&${new URLSearchParams({destination,travelmode:'driving'})}`;
        directions.target='_blank';
        directions.rel='noopener noreferrer';
        directions.textContent=hasCoords?'Get directions ↗':'Find on map (approximate) ↗';
        directions.setAttribute('aria-label',`${hasCoords?'Get directions to':'Find approximate map location for'} ${name}, ${wardName}, ${lgaName}`);
        item.append(directions);

        if(hasCoords){
          const map=document.createElement('a');
          const mapParams=new URLSearchParams({mlat:String(lat),mlon:String(lon)});
          map.href=`https://www.openstreetmap.org/?${mapParams}#map=16/${lat}/${lon}`;
          map.target='_blank';
          map.rel='noopener noreferrer';
          map.className='unit-map';
          map.textContent='View map ↗';
          map.setAttribute('aria-label',`View map for ${name}`);

          const riskButton=document.createElement('button');
          riskButton.type='button';
          riskButton.className='unit-risk';
          riskButton.textContent='Check nearby alerts';
          riskButton.addEventListener('click',async()=>{
            if(!unitId){riskButton.textContent='Alerts unavailable';return;}
            riskButton.disabled=true;
            riskButton.textContent='Checking…';
            try{
              const r=await apiFetch(`/api/polling-units/${encodeURIComponent(unitId)}/risk`);
              const risk=await r.json().catch(()=>null);
              if(!r.ok||!risk)throw new Error('Risk unavailable');
              const level=asText(risk.risk_level,'unknown');
              const score=asFiniteNumber(risk.risk_score);
              riskButton.textContent=level==='unknown'?'Risk unknown':`${level} risk${score===null?'':` · ${Math.round(score)}/100`}`;
              riskButton.title=asText(risk.note,'');
            }catch{riskButton.textContent='Alerts unavailable';riskButton.disabled=false;return;}
            riskButton.disabled=false;
          });
          item.append(map,riskButton);
        }
        return item;
      });

      if(typeof data?.notice==='string'&&data.notice){
        const note=document.createElement('p');
        note.className='lookup-note';
        note.textContent=data.notice;
        cards.push(note);
      }
      const shownTo=Math.max(pollingOffset+count,rows.length);
      const summary=document.createElement('p');
      summary.className='polling-count';
      summary.textContent=`Showing 1–${shownTo} of ${totalCount} polling units`;
      if(pollingOffset===0)result.replaceChildren(summary,...cards);
      else{
        result.querySelector('.polling-count')?.replaceWith(summary);
        result.querySelector('.load-more-units')?.remove();
        result.append(...cards);
      }
      if(pollingOffset+count<totalCount){
        const more=document.createElement('button');
        more.type='button';more.className='load-more-units';more.textContent='Load more polling units';
        more.addEventListener('click',()=>{pollingOffset+=count;loadPollingUnits();});
        result.append(more);
      }
    }else{
      result.textContent=typeof data?.notice==='string'&&data.notice?data.notice:'No matching verified record found. Check your PVC or INEC’s official locator.';
    }
  }catch{
    if(pollingOffset===0)result.textContent='Local lookup service is unavailable. Use INEC’s official polling-unit locator below.';
    else{
      const error=document.createElement('p');
      error.textContent='More local records could not be loaded. Please try again.';
      result.querySelector('.load-more-units')?.remove();
      result.append(error);
    }
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
  if(!weather||typeof weather!=='object'||!weather.available){
    return asText(weather?.message,'Weather forecast unavailable.');
  }
  const data=weather.data&&typeof weather.data==='object'?weather.data:{};
  const current=data.current&&typeof data.current==='object'?data.current:{};
  const daily=data.daily&&typeof data.daily==='object'?data.daily:{};
  const high=Array.isArray(daily.temperature_2m_max)?asFiniteNumber(daily.temperature_2m_max[0]):null;
  const low=Array.isArray(daily.temperature_2m_min)?asFiniteNumber(daily.temperature_2m_min[0]):null;
  const rain=Array.isArray(daily.precipitation_probability_max)?asFiniteNumber(daily.precipitation_probability_max[0]):null;
  const temp=asFiniteNumber(current.temperature_2m);
  const parts=[];
  if(temp!==null)parts.push(`${temp}°C now`);
  if(low!==null&&high!==null)parts.push(`${low}–${high}°C today`);
  if(rain!==null)parts.push(`${rain}% maximum rain chance today`);
  const provider=asText(weather.provider,'Weather');
  const location=asText(weather.location,asText(weather.state,'selected area'));
  const attribution=asText(weather.attribution,'Third-party forecast only; official alerts are separate.');
  return `${provider} forecast for ${location}${parts.length?`: ${parts.join(', ')}`:''}. ${attribution}`;
}
function formatAlert(alert){
  if(!alert||typeof alert!=='object')return null;
  const hazard=asText(alert.hazard,'Advisory');
  const details=asText(alert.details,'Details unavailable.');
  const severity=asFiniteNumber(alert.severity);
  const source=asText(alert.source,'Official source');
  return `${hazard}: ${details}${severity===null?'':` (${Math.round(severity)}/100, ${source})`}`;
}
document.querySelector('#check-alerts')?.addEventListener('click',async()=>{
  const state=(alertState&&alertState.value)||stateSelect?.value||'';
  const output=document.querySelector('#risk-result');
  if(!output)return;
  if(!state){output.textContent='Choose your state first.';return;}
  output.textContent='Checking current advisories…';
  try{
    const [riskResult,weatherResult]=await Promise.allSettled([
      apiFetch(`/api/risk?state=${encodeURIComponent(state)}`),
      apiFetch(`/api/weather/${encodeURIComponent(state)}`)
    ]);
    const riskResponse=riskResult.status==='fulfilled'?riskResult.value:null;
    const weatherResponse=weatherResult.status==='fulfilled'?weatherResult.value:null;
    const risk=riskResponse?.ok?await riskResponse.json().catch(()=>null):null;
    const weather=weatherResponse?.ok?await weatherResponse.json().catch(()=>null):null;
    const alerts=Array.isArray(risk?.alerts)?risk.alerts.map(formatAlert).filter(Boolean):[];
    const alertText=risk
      ?alerts.length?alerts.join(' · '):'No verified local hazard advisories are loaded. Check official alerts before travel; no report does not mean no risk.'
      :'Local hazard advisories are unavailable right now.';
    const weatherText=weather?formatWeather(weather):'Weather forecast is unavailable right now.';
    output.textContent=`${alertText} ${weatherText}`;
    const status=document.querySelector('#alert-status');
    if(status)status.textContent=risk?.alerts?.length
      ?'Verified advisories available'
      :weather?.available?'Open-Meteo forecast · no verified alerts'
      :risk?'No live provider data':'Advisories unavailable';
  }catch{
    output.textContent='Forecast and local advisory services are unavailable. Check official weather and emergency sources before travel.';
  }
});
const voiceButton=document.querySelector('#voice-button');
voiceButton?.addEventListener('click',()=>{
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){voiceButton.title='Voice input is not available in this browser';voiceButton.setAttribute('aria-disabled','true');return;}
  try{
    const recognition=new Recognition();
    recognition.lang=voiceLang[currentLang()]||'en-NG';
    recognition.interimResults=false;
    recognition.maxAlternatives=1;
    recognition.onresult=event=>{
      const transcript=event?.results?.[0]?.[0]?.transcript;
      if(typeof transcript!=='string'||!transcript.trim())return;
      const input=document.querySelector('#question');
      if(input)input.value=transcript.trim();
      document.querySelector('#chat-form')?.requestSubmit();
    };
    recognition.start();
  }catch{
    voiceButton.title='Voice input could not be started';
  }
});
const menuToggle=document.querySelector('#menu-toggle');
const desktopNav=document.querySelector('.desktop-nav');
function closeMenu(){
  if(!desktopNav||!menuToggle)return;
  desktopNav.classList.remove('mobile-nav');
  menuToggle.setAttribute('aria-expanded','false');
  menuToggle.setAttribute('aria-label','Open menu');
}
menuToggle?.addEventListener('click',()=>{
  if(!desktopNav)return;
  const opened=menuToggle.getAttribute('aria-expanded')==='true';
  menuToggle.setAttribute('aria-expanded',String(!opened));
  menuToggle.setAttribute('aria-label',opened?'Open menu':'Close menu');
  desktopNav.classList.toggle('mobile-nav',!opened);
});
desktopNav?.querySelectorAll('a').forEach(a=>a.addEventListener('click',closeMenu));
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu();});
document.addEventListener('click',e=>{
  if(!desktopNav?.classList.contains('mobile-nav'))return;
  if(desktopNav.contains(e.target)||menuToggle?.contains(e.target))return;
  closeMenu();
});
if('serviceWorker' in navigator && location.protocol.startsWith('http')){
  window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(()=>{});});
}
