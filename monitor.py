"""Conservative monitor: never equate missing text with availability unless date cell verified."""
import asyncio, datetime, json, os, re
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).parent
async def inspect(browser,site):
    result={'name':site.get('name',''),'date':site.get('date',''),'status':'판독 불가','reason':'예약 날짜의 상태를 확인하지 못했습니다.'}
    url=site.get('url','')
    if not url.startswith('https://'): result['reason']='HTTPS 주소가 아닙니다.';return result
    context=await browser.new_context(locale='ko-KR',timezone_id='Asia/Seoul')
    page=await context.new_page()
    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=30000)
        await page.wait_for_timeout(2500)
        # Navigation attempts are best-effort; never infer bookability from their success.
        for label in ['예약하기','상세보기','개인']:
            try:
                loc=page.get_by_text(label,exact=False)
                if await loc.count()==1 and await loc.first.is_visible():
                    await loc.first.click(timeout=3500)
                    await page.wait_for_timeout(1300)
            except Exception: pass
        target=site.get('date','')
        try: day=int(target[-2:])
        except: result['reason']='날짜 형식 오류';return result
        # A DOM date-cell must carry an unambiguous ISO date or full YYYY.MM.DD identifier.
        variants=[target,target.replace('-','.')]
        matches=[]
        for val in variants:
            matches+=await page.locator('[data-date="'+val+'"], [aria-label*="'+val+'"], [title*="'+val+'"]').all()
        matches=[m for m in matches if await m.is_visible()]
        if len(matches)!=1:
            result['reason']='대상 날짜 셀을 고유하게 식별하지 못했습니다. 카카오 달력 전용 판독기 검증 필요.'
            return result
        cell=matches[0]
        txt=await cell.inner_text(timeout=3000)
        if '예약마감' in txt:result.update(status='예약마감',reason='지정 날짜 셀에서 예약마감 확인')
        else:result.update(status='확인 필요',reason='지정 날짜 셀에서 예약마감 문구 미발견. 실제 예약 가능 여부는 미확정')
    except Exception as e:result['reason']='접속/탐색 오류: '+str(e)[:120]
    finally:await context.close()
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
    (ROOT/'data/status.json').write_text(json.dumps({'checked_at':now,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    # Optional Telegram alert only for candidates; not confirmed availability.
    token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
    if token and chat:
        import urllib.request,urllib.parse
        for r in results:
            if r['status']=='확인 필요':
                msg=f"[예약 확인 필요] {r['name']} {r['date']}\n예약마감 표시 미발견(예약 확정 아님). 직접 확인하세요."
                data=urllib.parse.urlencode({'chat_id':chat,'text':msg}).encode()
                try:urllib.request.urlopen(urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=data),timeout=10)
                except Exception as e:print('Telegram failed:',e)
if __name__=='__main__':asyncio.run(main())
