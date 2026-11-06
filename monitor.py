"""v1.6: conservative monitor and sanitized public API schema diagnostics."""
import asyncio, datetime, json, os, re, traceback, urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).parent
DIAG=ROOT/'diagnostics'
DIAG.mkdir(exist_ok=True)
def safe_name(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s)[:45] or 'site'

async def inspect(browser,site):
    result={'name':site.get('name',''),'date':site.get('date',''),'status':'판독 불가','reason':'예약 날짜의 상태를 확인하지 못했습니다.'}
    url=site.get('url','')
    if not url.startswith('https://'): result['reason']='HTTPS 주소가 아닙니다.';return result
    context=await browser.new_context(locale='ko-KR',timezone_id='Asia/Seoul', viewport={'width': 1280, 'height': 900}, is_mobile=False, has_touch=False, device_scale_factor=1)
    page=await context.new_page()
    trace=[]
    network=[]
    api_shapes=[]
    failures=[]
    console_errors=[]
    interesting=re.compile(r'api|calendar|schedule|ticket|booking|inventory|stock|slot|date|reserve|product|availability',re.I)
    def scrub_url(url):
        # Do not export authentication tokens, cookies, query parameters or personal data.
        parsed=urllib.parse.urlsplit(url)
        return parsed.scheme+'://'+parsed.netloc+parsed.path
    def response_hook(resp):
        req=resp.request
        u=scrub_url(resp.url)
        if req.resource_type in ('xhr','fetch') or interesting.search(urllib.parse.urlsplit(resp.url).path):
            network.append({'event':'response','method':req.method,'type':req.resource_type,'status':resp.status,'url':u})
    async def inspect_api_response(resp):
        """Record only structural metadata for public ticket API responses, never bodies."""
        path=urllib.parse.urlsplit(resp.url).path
        if resp.status != 200 or not path.startswith('/api/product/public/ticket/'):
            return
        try:
            data=await resp.json()
            seen=[]
            def walk(obj, prefix='', depth=0):
                if len(seen)>=120 or depth>5:return
                if isinstance(obj,dict):
                    for k,v in list(obj.items())[:65]:
                        key=str(k)
                        kp=(prefix+'.'+key).strip('.')
                        if isinstance(v,(dict,list)):
                            seen.append({'path':kp,'type':type(v).__name__,'length':len(v)})
                            walk(v,kp,depth+1)
                        else:
                            # No values are exported: response might contain personal information.
                            seen.append({'path':kp,'type':type(v).__name__})
                elif isinstance(obj,list) and obj:
                    walk(obj[0],prefix+'[0]',depth+1)
            walk(data)
            api_shapes.append({'path':path,'status':resp.status,'fields':seen})
        except Exception as e:
            api_shapes.append({'path':path,'error_type':type(e).__name__})
    pending=[]
    def schedule_api_inspection(resp):
        if resp.status==200 and '/api/product/public/ticket/' in resp.url:
            pending.append(asyncio.create_task(inspect_api_response(resp)))
    page.on('response',schedule_api_inspection)
    def request_failed(req):
        failures.append({'method':req.method,'type':req.resource_type,'url':scrub_url(req.url),'failure':str(req.failure)[:180]})
    def page_error(err):
        console_errors.append({'kind':'pageerror','message':str(err)[:350]})
    def console_hook(msg):
        if msg.type=='error':
            console_errors.append({'kind':'console','message':msg.text[:350]})
    page.on('response',response_hook)
    page.on('requestfailed',request_failed)
    page.on('pageerror',page_error)
    page.on('console',console_hook)
    key=safe_name(site.get('name','site'))+'_'+safe_name(site.get('date','date'))
    async def snapshot(stage):
        try:
            await page.screenshot(path=str(DIAG/(key+'_'+stage+'.png')),full_page=True,timeout=12000)
        except Exception as e:trace.append('screenshot error: '+str(e)[:100])
    def log(message):
        trace.append(message)
        print('['+key+'] '+message,flush=True)

    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=30000)
        await page.wait_for_timeout(2500)
        if '/install.html' in page.url:
            log('Kakao app bridge encountered; retrying original URL as desktop')
            await page.goto(url,wait_until='domcontentloaded',timeout=30000)
            await page.wait_for_timeout(2500)
        if '/install.html' in page.url:
            result['reason']='카카오톡 앱 실행 안내 페이지로 전환되어 예약 화면 접근 불가'
            await snapshot('00_app_bridge')
            return result
        # Some Kakao entry URLs show a landing page with a yellow 예약하기 button.
        booking_button=page.get_by_role('button',name=re.compile('예약하기'))
        if await booking_button.count() == 1:
            log('landing booking button found')
            await booking_button.click(timeout=10000)
            await page.wait_for_timeout(1800)
        if '/install.html' in page.url:
            result['reason']='예약하기 클릭 후 카카오톡 앱 실행 안내로 전환됨'
            await snapshot('00_app_bridge')
            return result
        log('initial URL: '+page.url)
        await snapshot('01_initial')
        # The saved Kakao DOM contains a clickable product button, not a clickable "상세보기" span.
        # Select the personal product button by its own title; never click the group ticket.
        product=page.locator('button.product_ticket').filter(has=page.locator('.tit_product',has_text=re.compile(r'입장권\s*\(개인\)')))
        count=await product.count()
        log('personal ticket buttons: '+str(count))
        if count!=1:
            result['reason']='개인 입장권 버튼을 고유하게 찾지 못했습니다.'
            await snapshot('02_no_personal_ticket')
            return result
        try:
            await product.click(timeout=12000)
            await page.wait_for_load_state('domcontentloaded',timeout=10000)
        except Exception as e:
            log('click/load note: '+str(e)[:180])
        await page.wait_for_timeout(5000)
        log('after personal click URL: '+page.url)
        await snapshot('02_personal_detail')
        # Kakao's client-side transition may display a blank ticket page in headless Chromium.
        # Retry the known ticket URL as a full document navigation, then reload if necessary.
        detail_url=page.url
        if not re.search(r'/detail/ticket/\d+',detail_url):
            result['reason']='개인 입장권 상세 주소로 이동하지 못했습니다.'
            return result
        async def calendar_loaded():
            try:
                await page.get_by_text('일정을 선택하세요',exact=False).first.wait_for(state='visible',timeout=8000)
                return True
            except Exception:
                return False
        loaded=await calendar_loaded()
        if not loaded:
            log('calendar missing after SPA transition; hard navigating to ticket URL')
            await page.goto(detail_url,wait_until='domcontentloaded',timeout=30000)
            await page.wait_for_timeout(3000)
            loaded=await calendar_loaded()
            await snapshot('03_direct_ticket')
        if not loaded:
            log('calendar missing after direct navigation; reload once')
            await page.reload(wait_until='domcontentloaded',timeout=30000)
            await page.wait_for_timeout(3000)
            loaded=await calendar_loaded()
            await snapshot('04_reloaded_ticket')
        if not loaded:
            log('calendar unavailable after all attempts; title='+repr(await page.title())+' body='+repr((await page.locator('body').inner_text())[:300]))
            result['reason']='개인 입장권 상세 주소에 도착했으나 달력이 로딩되지 않았습니다. 네트워크/JS 진단 파일 확인 필요.'
            return result
        target=site.get('date','')
        try:
            d=datetime.date.fromisoformat(target)
        except ValueError:
            result['reason']='감시 날짜 형식 오류 (YYYY-MM-DD)';return result
        text=await page.locator('body').inner_text(timeout=10000)
        await snapshot('05_calendar_loaded')
        log('calendar heading found')
        # Navigate only if the displayed month can be unambiguously identified.
        # Do not click guessed next-month buttons: that could silently inspect a wrong month.
        month_re=re.compile(rf'{d.year}\s*년\s*0?{d.month}\s*월')
        if not month_re.search(text):
            result['reason']=f'{d.year}년 {d.month}월 달력이 표시되지 않았습니다. 다른 월 자동 이동은 아직 미지원입니다.'
            log('target month not visible')
            return result
        log('target month confirmed')
        # Save DOM structures containing the target date for selector development.
        # A date is accepted only if its own container can be identified uniquely.
        candidates=await page.evaluate("""({iso, day}) => {
          const nodes=[...document.querySelectorAll('button,td,[role=gridcell],[data-date],[aria-label],li')];
          return nodes.filter(el => {
            const attrs=[el.getAttribute('data-date'),el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('datetime')].filter(Boolean).join(' ');
            const own=(el.innerText||'').trim();
            return attrs.includes(iso) || (own===String(day) && el.closest('[class*=calendar], [class*=date], [class*=day], table, [role=grid]'));
          }).slice(0,40).map(el=>({tag:el.tagName,outer:el.outerHTML.slice(0,1800),parent:el.parentElement?.outerHTML.slice(0,2600)}));
        }""",{'iso':target,'day':d.day})
        (DIAG/(key+'_date_candidates.json')).write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding='utf-8')
        log('candidate date nodes: '+str(len(candidates)))
        # Strict ISO-identified date cell. We intentionally do not claim availability
        # when only a bare day number is found, since adjacent-month days can repeat.
        selectors=[f'[data-date="{target}"]',f'[datetime="{target}"]',f'[aria-label*="{target}"]',f'[title*="{target}"]',f'[data-date="{target.replace("-", ".")}"]']
        unique=[]
        for selector in selectors:
            for loc in await page.locator(selector).all():
                if await loc.is_visible():
                    unique.append(loc)
        if len(unique)!=1:
            result['reason']='달력 진입 성공. 다만 날짜 셀의 고유 식별자가 확인되지 않아 판독을 보류했습니다.'
            await snapshot('03_calendar_date_unresolved')
            return result
        cell=unique[0]
        cell_text=await cell.inner_text(timeout=3000)
        cell_class=(await cell.get_attribute('class')) or ''
        disabled=(await cell.get_attribute('disabled')) is not None or (await cell.get_attribute('aria-disabled'))=='true'
        log('date cell text: '+repr(cell_text[:160]))
        if '예약마감' in cell_text:
            result.update(status='예약마감',reason='지정 날짜 셀에 예약마감 표시 확인')
        elif disabled or any(x in cell_class.lower() for x in ('disabled','soldout','inactive')):
            result.update(status='확인 필요',reason='예약마감 문구는 없지만 날짜가 비활성 상태입니다. 예약 가능으로 판단하지 않습니다.')
        else:
            result.update(status='확인 필요',reason='지정 날짜 셀에 예약마감 문구 없음. 실제 회차 선택 가능 여부는 확인 필요')
        await snapshot('03_calendar_checked')
    except Exception as e:
        result['reason']='접속/탐색 오류: '+str(e)[:120]
        log('ERROR: '+repr(e))
        await snapshot('error')
    finally:
        result['final_url']=page.url
        result['diagnostics']=key
        (DIAG/(key+'_trace.json')).write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
        # Diagnostics: request paths/statuses and JSON key names/types only; never bodies, cookies or query strings.
        if pending:
            await asyncio.gather(*pending,return_exceptions=True)
        report={'final_url':scrub_url(page.url),'requests':network[-300:],'failed_requests':failures[-100:],'javascript_errors':console_errors[-100:],'public_ticket_api_shapes':api_shapes[-30:]}
        (DIAG/(key+'_network.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        log(f'network diagnostic: {len(network)} responses, {len(failures)} failed requests, {len(console_errors)} JS/console errors')
        try:
            html=await page.content()
            (DIAG/(key+'_dom.html')).write_text(html[:1500000],encoding='utf-8')
        except Exception:pass
        await context.close()
    return result
async def main():
    sites=json.loads((ROOT/'sites.json').read_text(encoding='utf-8'))[:5]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        results=[]
        for s in sites:
            if s.get('enabled'):results.append(await inspect(browser,s))
        await browser.close()
    now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec='seconds')
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'data/status.json').write_text(json.dumps({'checked_at':now,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    # Optional Telegram alert only for candidates; not confirmed availability.
    token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
    if token and chat:
        import urllib.request,urllib.parse
        for r in results:
            if r['status']=='예약 가능':
                msg=f"[예약 가능] {r['name']} {r['date']}\n예약 가능 회차가 확인되었습니다."
                data=urllib.parse.urlencode({'chat_id':chat,'text':msg}).encode()
                try:urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=data),timeout=10)
                except Exception as e:print('Telegram failed:',e)
if __name__=='__main__':asyncio.run(main())
