from calendar import isleap
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_URL = 'https://raw.githubusercontent.com/greatsong/modudata/main/data/seoul.csv'

@st.cache_data(ttl=3600, show_spinner=False)
def load_data():
    local = Path(__file__).with_name('seoul.csv')
    if local.exists():
        raw = local.read_bytes()
    else:
        with urlopen(DATA_URL, timeout=30) as response:
            raw = response.read()
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            df = pd.read_csv(BytesIO(raw), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('CSV 파일의 문자 인코딩을 확인해 주세요.')
    df.columns = df.columns.str.strip()
    required = {'날짜', '지점', '평균기온'}
    if not required.issubset(df.columns):
        raise ValueError('날짜·지점·평균기온 열이 필요합니다.')
    df['날짜'] = pd.to_datetime(df['날짜'].astype(str).str.strip(), errors='coerce')
    df['평균기온'] = pd.to_numeric(df['평균기온'], errors='coerce')
    df = df[pd.to_numeric(df['지점'], errors='coerce').eq(108)]
    df = df.dropna(subset=['날짜']).sort_values('날짜').drop_duplicates('날짜')
    if df.empty or df['평균기온'].notna().sum() == 0:
        raise ValueError('서울(108 지점)의 유효한 기온 자료가 없습니다.')
    return df


def annual_means(df):
    first, last = int(df['날짜'].dt.year.min()), int(df['날짜'].dt.year.max())
    annual = df.groupby(df['날짜'].dt.year)['평균기온'].agg(['mean', 'count'])
    annual = annual.reindex(range(first, last + 1))
    annual.index.name = '연도'
    annual.columns = ['연평균 기온(℃)', '관측일 수']
    annual['관측일 수'] = annual['관측일 수'].fillna(0).astype(int)
    annual['연간 일수'] = [366 if isleap(y) else 365 for y in annual.index]
    annual['관측률(%)'] = annual['관측일 수'] / annual['연간 일수'] * 100
    # 관측률 95%는 이 앱의 분석 기준이며 공식 연평균 산출 기준이 아닙니다.
    annual.loc[annual['관측률(%)'] < 95, '연평균 기온(℃)'] = float('nan')
    annual['10년 이동평균(℃)'] = annual['연평균 기온(℃)'].rolling(10, min_periods=10).mean()
    return annual


def main():
    st.set_page_config(page_title='서울의 100년 기온 변화', page_icon='🌡️', layout='wide')
    st.title('서울의 100년 기온 변화')
    st.write('해마다 달라지는 기온과 10년 이동평균으로 장기 변화를 살펴보세요.')
    try:
        with st.spinner('서울 기온 데이터를 불러오는 중입니다…'):
            df = load_data()
    except Exception as exc:
        st.error('데이터를 불러오지 못했습니다. 인터넷 연결이나 같은 폴더의 seoul.csv를 확인해 주세요.')
        with st.expander('오류 내용'):
            st.text(str(exc))
        st.stop()

    latest = df['날짜'].max()
    # 연말까지 기록이 있는 연도만 기본 분석 기간의 끝으로 사용합니다.
    end = int(latest.year) if (latest.month, latest.day) == (12, 31) else int(latest.year) - 1
    start = max(int(df['날짜'].dt.year.min()), end - 99)
    if end < start:
        st.warning('완료된 연도의 자료가 아직 없습니다.')
        st.stop()
    annual = annual_means(df)
    selected = annual.loc[start:end].copy()
    st.caption(f'분석 기간: {start}–{end}년 · 원본 마지막 날짜: {latest:%Y-%m-%d}')
    if end - start + 1 < 100:
        st.info('원본 자료가 100년보다 짧아 이용 가능한 기간을 표시합니다.')

    early = selected.iloc[:10]['연평균 기온(℃)'].dropna()
    recent = selected.iloc[-10:]['연평균 기온(℃)'].dropna()
    a, b, c = st.columns(3)
    a.metric(f'처음 10년 평균 ({start}–{min(start + 9, end)})', f'{early.mean():.2f} ℃' if len(early) == 10 else '자료 부족')
    b.metric(f'마지막 10년 평균 ({max(start, end - 9)}–{end})', f'{recent.mean():.2f} ℃' if len(recent) == 10 else '자료 부족')
    c.metric('두 기간의 기온 차이', f'{recent.mean() - early.mean():+.2f} ℃' if len(early) == len(recent) == 10 else '자료 부족')

    fig = go.Figure()
    for column, label, color, width in [
        ('연평균 기온(℃)', '연평균 기온', '#6294ba', 1.8),
        ('10년 이동평균(℃)', '10년 이동평균', '#e2663b', 4),
    ]:
        fig.add_trace(go.Scatter(
            x=selected.index, y=selected[column], name=label,
            mode='lines', line=dict(color=color, width=width), connectgaps=False,
            hovertemplate='%{x}년<br>%{y:.2f} ℃<extra>' + label + '</extra>',
        ))
    fig.update_layout(
        height=500, template='plotly_white',
        xaxis_title='연도', yaxis_title='기온 (℃)',
        font=dict(family='sans-serif'), hovermode='x unified',
        legend=dict(orientation='h', y=1.12, x=0),
        margin=dict(l=30, r=20, t=65, b=30),
    )
    fig.update_xaxes(tickformat='d')
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})
    missing = selected.index[selected['연평균 기온(℃)'].isna()].tolist()
    if missing:
        st.caption('관측률 부족으로 제외한 해: ' + ', '.join(map(str, missing)) + '년')
    st.caption('연평균은 일평균 기온의 산술평균입니다. 관측률 95% 미만인 해는 제외하며 빈 구간은 연결하지 않습니다. '
               '10년 이동평균은 해당 연도와 앞선 9년의 연평균을 평균한 값으로, 10개 연도가 모두 유효할 때만 표시합니다. '
               '기간 시작 부분의 이동평균에는 표시 기간 이전 자료가 포함될 수 있습니다.')
    with st.expander('연도별 데이터 보기'):
        st.dataframe(selected.round(2), width='stretch')
    st.markdown(f'[원본 서울 기온 데이터]({DATA_URL})')


if __name__ == '__main__':
    main()
