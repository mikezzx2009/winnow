import { createContext, useContext } from 'react'

// 当前选中的账号上下文，供各页面读取 accountId 并在切换时重新加载。
export const AccountContext = createContext({
  accountId: null,
  accounts: [],
  setAccountId: () => {},
  reloadAccounts: () => {},
})

export const useAccount = () => useContext(AccountContext)
